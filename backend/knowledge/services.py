import unicodedata
import uuid
from collections import deque
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Max

from problem.models import Problem

from .api import KnowledgeError, category, code, integer, text, weight
from .models import (KnowledgeDependency, KnowledgeDependencyChangeRequest,
                     KnowledgeMappingBatch, KnowledgePoint, KnowledgeReviewEvent,
                     ProblemKnowledge)


def normalized(value):
    cleaned = " ".join(unicodedata.normalize("NFKC", text(value, 1, 128)).split())
    result = "".join(char.lower() if "A" <= char <= "Z" else char for char in cleaned)
    if not result or len(result) > 128:
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "Invalid normalized name")
    return result


def point_fields(data, creating=False):
    result = {}
    if "code" in data:
        if not creating:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        result["code"] = code(data["code"])
    if "name" in data:
        result["name"] = text(data["name"], 1, 128)
        result["normalized_name"] = normalized(result["name"])
    if "description" in data:
        result["description"] = text(data["description"], 0, 5000)
    if "category" in data:
        result["category"] = category(data["category"])
        if result["category"] is None:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
    if "level" in data:
        result["level"] = integer(data["level"], 1, 5)
    if "aliases" in data:
        aliases = data["aliases"]
        if not isinstance(aliases, list) or len(aliases) > 20:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        seen = set()
        result["aliases"] = []
        for alias in aliases:
            value = text(alias, 1, 128)
            key = normalized(value)
            if key in seen:
                continue
            seen.add(key)
            result["aliases"].append(value)
    if "metadata" in data:
        metadata = data["metadata"]
        if not isinstance(metadata, dict) or set(metadata) - {"course_chapter", "display_order"}:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        if "course_chapter" in metadata:
            text(metadata["course_chapter"], 0, 128)
        if "display_order" in metadata:
            integer(metadata["display_order"], 0, 2147483647)
        result["metadata"] = metadata
    return result


def point_referenced(point, pending_only=False):
    dependencies = KnowledgeDependency.objects.filter(prerequisite=point) | KnowledgeDependency.objects.filter(dependent=point)
    requests = KnowledgeDependencyChangeRequest.objects.filter(prerequisite=point) | KnowledgeDependencyChangeRequest.objects.filter(dependent=point)
    mappings = ProblemKnowledge.objects.filter(knowledge_point=point)
    if pending_only:
        requests = requests.filter(status="pending")
    if dependencies.exists() or requests.exists() or mappings.exists():
        return True
    for batch in KnowledgeMappingBatch.objects.filter(status="pending") if pending_only else KnowledgeMappingBatch.objects.all():
        if any(item.get("knowledge_code") == point.code for item in batch.payload.get("mappings", [])):
            return True
    return False


def dependency_state(edge):
    if not edge:
        return None
    return {"prerequisite_code": edge.prerequisite.code, "dependent_code": edge.dependent.code,
            "relation_type": edge.relation_type, "weight": float(edge.weight), "source": edge.source,
            "confidence": float(edge.confidence), "version": edge.version, "updated_time": edge.updated_time.isoformat()}


def dependency_proposal(change):
    if change.operation == "delete":
        return None
    return {"prerequisite_code": change.prerequisite.code, "dependent_code": change.dependent.code,
            "relation_type": change.relation_type, "weight": float(change.weight)}


def dependency_snapshot(change, before):
    return {"snapshot_type": "dependency_change", "request_id": str(change.id), "operation": change.operation,
            "target_dependency_id": change.target_dependency_id, "base_version": change.base_version,
            "before": before, "proposed": dependency_proposal(change), "status": change.status}


def mapping_snapshot(batch):
    return {"snapshot_type": "problem_mapping", "review_batch_id": str(batch.id), "problem_id": batch.problem_id,
            "batch_version": batch.batch_version, "base_version": batch.base_version,
            "approved_version": batch.approved_version, "status": batch.status, "mappings": batch.payload["mappings"]}


def audit(object_type, object_key, version, action, actor, snapshot, request_id, reason=""):
    KnowledgeReviewEvent.objects.create(object_type=object_type, object_key=str(object_key), object_version=version,
                                        action=action, actor=actor, reason=reason, snapshot=snapshot, request_id=request_id)


def active_point(point_code):
    try:
        return KnowledgePoint.objects.get(code=code(point_code), status="active")
    except KnowledgePoint.DoesNotExist:
        raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)


def no_cycle(prerequisite_id, dependent_id, replacing_id=None):
    if prerequisite_id == dependent_id:
        raise KnowledgeError("KNOWLEDGE_SELF_DEPENDENCY", 422)
    adjacency = {}
    for src, dst in KnowledgeDependency.objects.exclude(id=replacing_id).values_list("prerequisite_id", "dependent_id"):
        adjacency.setdefault(src, set()).add(dst)
    queue = deque([dependent_id])
    visited = set(queue)
    while queue:
        current = queue.popleft()
        if current == prerequisite_id:
            raise KnowledgeError("KNOWLEDGE_DEPENDENCY_CYCLE", 422)
        for neighbor in adjacency.get(current, ()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)


def create_dependency_request(data, user, request_id):
    operation = data.get("operation")
    if operation not in {"create", "update", "delete"}:
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
    fields = {"operation", "reason"}
    if operation in {"update", "delete"}:
        fields |= {"target_dependency_id", "base_version"}
    if operation in {"create", "update"}:
        fields |= {"prerequisite_code", "dependent_code", "relation_type", "weight"}
    if set(data) != fields:
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
    reason = text(data["reason"], 2, 500)
    with transaction.atomic():
        # Serialize competing writers, including two creates for the same directed pair.
        list(KnowledgePoint.objects.select_for_update().order_by("id").values_list("id", flat=True))
        target = None
        proposed = {}
        if operation != "create":
            target_id = integer(data["target_dependency_id"], 1, 2147483647)
            try:
                target = KnowledgeDependency.objects.select_for_update().select_related("prerequisite", "dependent").get(id=target_id)
            except KnowledgeDependency.DoesNotExist:
                raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)
            if target.version != integer(data["base_version"], 1, 2147483647):
                raise KnowledgeError("KNOWLEDGE_VERSION_CONFLICT", 409)
            if KnowledgeDependencyChangeRequest.objects.filter(target_dependency=target, status="pending").exists():
                raise KnowledgeError("KNOWLEDGE_REVIEW_CONFLICT", 409)
        if operation != "delete":
            prerequisite = active_point(data["prerequisite_code"])
            dependent = active_point(data["dependent_code"])
            if prerequisite.id == dependent.id:
                raise KnowledgeError("KNOWLEDGE_SELF_DEPENDENCY", 422)
            if data["relation_type"] not in {"required", "recommended"}:
                raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
            proposed = {"prerequisite": prerequisite, "dependent": dependent, "relation_type": data["relation_type"], "weight": weight(data["weight"])}
            existing = KnowledgeDependency.objects.filter(prerequisite=prerequisite, dependent=dependent).exists()
            pending = KnowledgeDependencyChangeRequest.objects.filter(operation="create", status="pending",
                                                                      prerequisite=prerequisite, dependent=dependent).exists()
            if operation == "create" and (existing or pending):
                raise KnowledgeError("KNOWLEDGE_DEPENDENCY_EXISTS", 409)
        try:
            change = KnowledgeDependencyChangeRequest.objects.create(operation=operation, target_dependency=target,
                                                                     base_version=target.version if target else None,
                                                                     reason=reason, submitted_by=user, **proposed)
        except IntegrityError:
            raise KnowledgeError("KNOWLEDGE_REVIEW_CONFLICT", 409)
        audit("dependency_change", change.id, target.version if target else 0, "submitted", user,
              dependency_snapshot(change, dependency_state(target)), request_id)
        return change


def validate_mapping_items(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
    seen = set()
    validated = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"knowledge_code", "role", "weight"}:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        point_code = code(item["knowledge_code"])
        if point_code in seen or item["role"] not in {"primary", "secondary", "prerequisite"}:
            raise KnowledgeError("KNOWLEDGE_MAPPING_INVALID", 422)
        active_point(point_code)
        seen.add(point_code)
        validated.append({"knowledge_code": point_code, "role": item["role"], "weight": float(weight(item["weight"], "KNOWLEDGE_MAPPING_INVALID")),
                          "source": "manual", "confidence": 1.0})
    if sum(item["role"] == "primary" for item in validated) != 1:
        raise KnowledgeError("KNOWLEDGE_MAPPING_INVALID", 422)
    return validated


def permitted_problem(problem_id, user):
    try:
        problem = Problem.objects.get(id=integer(problem_id, 1, 2147483647), contest__isnull=True)
    except Problem.DoesNotExist:
        raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)
    if not user.is_super_admin() and (user.problem_permission == "None" or
                                      (user.problem_permission == "Own" and problem.created_by_id != user.id)):
        raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)
    return problem


def approved_version(problem):
    return KnowledgeMappingBatch.objects.filter(problem=problem, approved_version__isnull=False).aggregate(value=Max("approved_version"))["value"] or 0


def submit_mapping(problem, data, user, request_id):
    if set(data) != {"base_version", "mappings"}:
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
    base = integer(data["base_version"], 0, 2147483647)
    items = validate_mapping_items(data["mappings"])
    with transaction.atomic():
        list(KnowledgePoint.objects.select_for_update().filter(code__in=[item["knowledge_code"] for item in items]).order_by("id"))
        for item in items:
            active_point(item["knowledge_code"])
        Problem.objects.select_for_update().get(id=problem.id)
        if base != approved_version(problem):
            raise KnowledgeError("KNOWLEDGE_VERSION_CONFLICT", 409)
        if KnowledgeMappingBatch.objects.filter(problem=problem, status="pending").exists():
            raise KnowledgeError("KNOWLEDGE_REVIEW_CONFLICT", 409)
        next_version = (KnowledgeMappingBatch.objects.filter(problem=problem).aggregate(value=Max("batch_version"))["value"] or 0) + 1
        batch_id = uuid.uuid4()
        payload = {"snapshot_type": "problem_mapping", "review_batch_id": str(batch_id), "problem_id": problem.id,
                   "batch_version": next_version, "base_version": base, "approved_version": None,
                   "status": "pending", "mappings": items}
        try:
            batch = KnowledgeMappingBatch.objects.create(id=batch_id, problem=problem, batch_version=next_version, base_version=base,
                                                         payload=payload, submitted_by=user)
        except IntegrityError:
            raise KnowledgeError("KNOWLEDGE_REVIEW_CONFLICT", 409)
        audit("problem_mapping", batch.id, batch.batch_version, "submitted", user, mapping_snapshot(batch), request_id)
        return batch


def parse_expected(value, actual):
    from django.utils.dateparse import parse_datetime
    expected = parse_datetime(value) if isinstance(value, str) else None
    if expected is None or expected.tzinfo is None:
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
    if expected != actual:
        raise KnowledgeError("KNOWLEDGE_VERSION_CONFLICT", 409)


def review_dependency(change, action, user, request_id, reason=""):
    if change.submitted_by_id == user.id:
        raise KnowledgeError("KNOWLEDGE_SELF_REVIEW_FORBIDDEN", 403)
    if change.status != "pending":
        raise KnowledgeError("KNOWLEDGE_REVIEW_CONFLICT", 409)
    target = None
    if change.target_dependency_id:
        try:
            target = KnowledgeDependency.objects.select_for_update().select_related("prerequisite", "dependent").get(id=change.target_dependency_id)
        except KnowledgeDependency.DoesNotExist:
            raise KnowledgeError("KNOWLEDGE_VERSION_CONFLICT", 409)
        if target.version != change.base_version:
            raise KnowledgeError("KNOWLEDGE_VERSION_CONFLICT", 409)
    before = dependency_state(target)
    if action == "approve":
        if change.operation != "delete":
            prerequisite = active_point(change.prerequisite.code)
            dependent = active_point(change.dependent.code)
            duplicate = KnowledgeDependency.objects.filter(prerequisite=prerequisite, dependent=dependent).exclude(id=target.id if target else None).exists()
            if duplicate:
                raise KnowledgeError("KNOWLEDGE_DEPENDENCY_EXISTS", 409)
            no_cycle(prerequisite.id, dependent.id, target.id if target else None)
        if change.operation == "create":
            target = KnowledgeDependency.objects.create(prerequisite=prerequisite, dependent=dependent,
                                                        relation_type=change.relation_type, weight=change.weight, created_by=user)
        elif change.operation == "update":
            target.prerequisite = prerequisite
            target.dependent = dependent
            target.relation_type = change.relation_type
            target.weight = change.weight
            target.version += 1
            target.save()
        else:
            target.delete()
        change.status = "approved"
        version = target.version if change.operation != "delete" else change.base_version
    else:
        change.status = "rejected"
        change.review_reason = reason
        version = target.version if target else 0
    change.reviewed_by = user
    change.save(update_fields=["status", "review_reason", "reviewed_by", "updated_time"])
    audit("dependency_change", change.id, version, "approved" if action == "approve" else "rejected", user,
          dependency_snapshot(change, before), request_id, reason)


def review_mapping(batch, action, user, request_id, reason=""):
    if batch.submitted_by_id == user.id:
        raise KnowledgeError("KNOWLEDGE_SELF_REVIEW_FORBIDDEN", 403)
    if batch.status != "pending":
        raise KnowledgeError("KNOWLEDGE_REVIEW_CONFLICT", 409)
    list(KnowledgePoint.objects.select_for_update().filter(code__in=[item["knowledge_code"] for item in batch.payload["mappings"]]).order_by("id"))
    Problem.objects.select_for_update().get(id=batch.problem_id)
    current_version = approved_version(batch.problem)
    if batch.base_version != current_version:
        raise KnowledgeError("KNOWLEDGE_VERSION_CONFLICT", 409)
    if action == "approve":
        for item in batch.payload["mappings"]:
            active_point(item["knowledge_code"])
        previous = KnowledgeMappingBatch.objects.filter(problem=batch.problem, status="approved").first()
        if previous:
            previous.status = "superseded"
            previous.payload = mapping_snapshot(previous)
            previous.save(update_fields=["status", "payload", "updated_time"])
            audit("problem_mapping", previous.id, previous.batch_version, "replaced", user, mapping_snapshot(previous), request_id, "Replaced by approved batch")
        ProblemKnowledge.objects.filter(problem=batch.problem).delete()
        for item in batch.payload["mappings"]:
            ProblemKnowledge.objects.create(problem=batch.problem, knowledge_point=active_point(item["knowledge_code"]),
                                            role=item["role"], weight=Decimal(str(item["weight"])), reviewed_by=user)
        batch.status = "approved"
        batch.approved_version = current_version + 1
    else:
        batch.status = "rejected"
        batch.reason = reason
    batch.reviewed_by = user
    batch.payload = mapping_snapshot(batch)
    batch.save(update_fields=["status", "approved_version", "reason", "reviewed_by", "payload", "updated_time"])
    audit("problem_mapping", batch.id, batch.batch_version, "approved" if action == "approve" else "rejected",
          user, mapping_snapshot(batch), request_id, reason)

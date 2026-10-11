"""Knowledge writes share one transaction lock, then take row locks.

The PostgreSQL advisory lock protects the *whole* graph and all new references,
including disjoint endpoints. Row locks alone cannot prevent concurrent cycles.
SQLite is supported only for serial unit tests, never as a concurrency substitute.
"""
from collections import defaultdict
from contextlib import contextmanager
from decimal import Decimal
from uuid import UUID

from django.apps import apps
from django.db import OperationalError, connection, transaction
from django.db.models import Max, Q
from django.db.models.deletion import ProtectedError

from account.models import AdminType, ProblemPermission
from problem.models import Problem
from utils.contract_api import ContractError

from .models import (KnowledgeDependency, KnowledgeDependencyChangeRequest, KnowledgeMappingBatch,
                     KnowledgePoint, KnowledgeReviewEvent, ProblemKnowledge)
from .serializers import dependency_state, normalize_name


KNOWLEDGE_WRITE_LOCK = 1263552848


def error(code, message, status=409, details=None):
    raise ContractError("KNOWLEDGE_" + code, message, status=status, details=details)


def require_admin(user, super_only=False):
    if not user or not user.is_authenticated or user.is_disabled:
        error("AUTH_REQUIRED", "请先登录", 401)
    if user.admin_type == AdminType.SUPER_ADMIN:
        return
    if (super_only or user.admin_type != AdminType.ADMIN
            or user.problem_permission not in (ProblemPermission.ALL, ProblemPermission.OWN)):
        error("PERMISSION_DENIED", "没有知识模块操作权限", 403)


def problem_scope_filter(user):
    require_admin(user)
    scope = Q(contest__isnull=True)
    if user.admin_type != AdminType.SUPER_ADMIN and user.problem_permission == ProblemPermission.OWN:
        scope &= Q(created_by=user)
    return scope


def problem_scope(user):
    return Problem.objects.filter(problem_scope_filter(user))


def get_problem(user, problem_id, lock=False):
    queryset = problem_scope(user)
    if lock:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(pk=problem_id)
    except Problem.DoesNotExist:
        error("NOT_FOUND", "题目不存在或不在权限范围", 404)


@contextmanager
def knowledge_write():
    try:
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '5s'")
                    cursor.execute("SET LOCAL statement_timeout = '30s'")
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [KNOWLEDGE_WRITE_LOCK])
            yield
    except OperationalError as exc:
        if getattr(exc.__cause__, "pgcode", None) in ("55P03", "57014", "40P01", "40001"):
            raise ContractError("KNOWLEDGE_VERSION_CONFLICT", "并发写入繁忙，请刷新后重试", 409, retryable=True) from None
        raise


def get_point(code, lock=False, active=False):
    queryset = KnowledgePoint.objects.select_related("created_by")
    if active:
        queryset = queryset.filter(status="active")
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    try:
        return queryset.get(code=code)
    except KnowledgePoint.DoesNotExist:
        error("NOT_FOUND", "知识点不存在", 404)


def _check_unique_point(data, exclude=None):
    queryset = KnowledgePoint.objects.all()
    if exclude:
        queryset = queryset.exclude(pk=exclude)
    if "code" in data and queryset.filter(code=data["code"]).exists():
        error("CODE_CONFLICT", "知识点 code 已存在")
    if "name" in data and queryset.filter(normalized_name=normalize_name(data["name"])).exists():
        error("NAME_CONFLICT", "知识点名称已存在")


def create_point(user, data):
    require_admin(user, super_only=True)
    with knowledge_write():
        _check_unique_point(data)
        return KnowledgePoint.objects.create(**data, normalized_name=normalize_name(data["name"]), created_by=user)


def _batch_references(code, pending_only):
    queryset = KnowledgeMappingBatch.objects.all()
    if pending_only:
        queryset = queryset.filter(status="pending")
    if connection.vendor == "postgresql":
        return queryset.filter(payload__contains=[{"knowledge_code": code}]).exists()
    return any(any(item["knowledge_code"] == code for item in payload)
               for payload in queryset.values_list("payload", flat=True).iterator())


def has_references(point, pending_only=False):
    if (KnowledgeDependency.objects.filter(Q(prerequisite=point) | Q(dependent=point)).exists()
            or ProblemKnowledge.objects.filter(knowledge_point=point).exists()):
        return True
    changes = KnowledgeDependencyChangeRequest.objects.all()
    if pending_only:
        changes = changes.filter(status="pending")
    # The immutable before state retains references after the target FK is cleared.
    if changes.filter(Q(prerequisite=point) | Q(dependent=point)
                      | Q(before__prerequisite_code=point.code) | Q(before__dependent_code=point.code)).exists():
        return True
    if _batch_references(point.code, pending_only):
        return True
    for relation in point._meta.related_objects:
        model = relation.related_model
        if model._meta.app_label == "knowledge":
            continue
        queryset = model._default_manager.filter(**{relation.field.name: point})
        if pending_only:
            label = model._meta.label_lower
            if label == "learning.ratinghistory":
                continue
            if label == "learning.learningpath":
                queryset = queryset.filter(status="active")
            elif label == "learning.learningpathstep":
                queryset = queryset.filter(learning_path__status="active", status__in=("pending", "in_progress"))
            elif label == "problem_import.externaltagmapping":
                queryset = queryset.filter(status__in=("pending", "active"))
            elif label == "agent_service.errorpattern":
                queryset = queryset.filter(review_status__in=("pending", "approved"))
        if queryset.exists():
            return True
    return _learning_event_references(point, pending_only) or _rag_references(point, pending_only)


def _learning_event_references(point, pending_only):
    if not apps.is_installed("learning"):
        return False
    queryset = apps.get_model("learning", "LearningSubmissionEvent").objects.all()
    if pending_only:
        queryset = queryset.filter(status__in=("pending", "failed"))
    if connection.vendor == "postgresql":
        return queryset.filter(payload__mappings__contains=[{"knowledge_id": point.pk}]).exists()
    return any(any(item.get("knowledge_id") == point.pk for item in payload.get("mappings", []))
               for payload in queryset.values_list("payload", flat=True).iterator())


def _rag_references(point, pending_only):
    if not apps.is_installed("rag"):
        return False
    for name in ("RagDocument", "RagChunk"):
        queryset = apps.get_model("rag", name).objects.all()
        if pending_only:
            queryset = queryset.filter(**{"status" if name == "RagDocument" else "document__status": "active"})
        if queryset.filter(metadata__knowledge_id=point.pk).exists():
            return True
    return False


def update_point(user, code, data):
    require_admin(user, super_only=True)
    with knowledge_write():
        point = get_point(code, lock=True)
        if data["version"] != point.version:
            error("VERSION_CONFLICT", "知识点版本已变化")
        status = data.get("status", point.status)
        if status != point.status:
            if (point.status, status) not in (("draft", "active"), ("active", "deprecated")):
                error("STATE_CONFLICT", "不允许此状态变更")
            if status == "deprecated" and has_references(point, pending_only=True):
                error("STATE_CONFLICT", "知识点仍被正式数据或待审申请引用")
        _check_unique_point(data, exclude=point.pk)
        changed = False
        for key, value in data.items():
            if key != "version" and getattr(point, key) != value:
                setattr(point, key, value)
                changed = True
        if changed:
            point.normalized_name = normalize_name(point.name)
            point.version += 1
            point.save()
        return point


def record_event(object_type, key, version, action, actor, snapshot, request_id, reason=""):
    return KnowledgeReviewEvent.objects.create(object_type=object_type, object_key=str(key), object_version=version,
                                               action=action, actor=actor, snapshot=snapshot,
                                               request_id=request_id, reason=reason)


def delete_point(user, code, data, request_id):
    require_admin(user, super_only=True)
    with knowledge_write():
        point = get_point(code, lock=True)
        if data["version"] != point.version:
            error("VERSION_CONFLICT", "知识点版本已变化")
        if point.status != "draft" or has_references(point):
            error("STATE_CONFLICT", "仅可删除从未引用的草稿")
        before = {key: getattr(point, key) for key in ("code", "name", "category", "level", "status", "version")}
        record_event("knowledge_point", code, point.version, "deleted", user,
                     {"snapshot_type": "knowledge_point", "before": before, "after": None}, request_id, data["reason"])
        try:
            point.delete()
        except ProtectedError:
            # Other installed producers may add PROTECT references. Keep the
            # conflict envelope and roll back the just-created deletion event.
            error("STATE_CONFLICT", "知识点仍被其他业务数据引用")


def get_dependency(dependency_id, lock=False):
    queryset = KnowledgeDependency.objects.select_related("prerequisite__created_by", "dependent__created_by")
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    try:
        return queryset.get(pk=dependency_id)
    except KnowledgeDependency.DoesNotExist:
        error("NOT_FOUND", "依赖不存在", 404)


def _validate_edge(prerequisite, dependent, exclude=None):
    if prerequisite.status != "active" or dependent.status != "active":
        error("STATE_CONFLICT", "依赖两端必须为 active 知识点")
    if prerequisite.pk == dependent.pk:
        error("SELF_DEPENDENCY", "知识点不能依赖自身", 422)
    edges = KnowledgeDependency.objects.all()
    if exclude:
        edges = edges.exclude(pk=exclude)
    if edges.filter(prerequisite=prerequisite, dependent=dependent).exists():
        error("DEPENDENCY_EXISTS", "同向正式依赖已存在")
    # Adding p -> d forms a cycle exactly when d already reaches p.
    graph = defaultdict(list)
    for source, target in edges.values_list("prerequisite_id", "dependent_id"):
        graph[source].append(target)
    visited, stack = set(), [dependent.pk]
    while stack:
        node = stack.pop()
        if node == prerequisite.pk:
            error("DEPENDENCY_CYCLE", "拟提交依赖形成有向环", 422)
        if node not in visited:
            visited.add(node)
            stack.extend(graph[node])


def change_snapshot(change):
    return {"snapshot_type": "dependency_change", "request_id": str(change.pk), "operation": change.operation,
            "original_target_id": change.original_target_id, "base_version": change.base_version,
            "before": change.before, "proposed": change.proposed, "status": change.status}


def submit_dependency(user, data, request_id):
    require_admin(user, super_only=True)
    with knowledge_write():
        operation = data["operation"]
        target, prerequisite, dependent, proposed = None, None, None, None
        if operation != "create":
            target = get_dependency(data["target_dependency_id"], lock=True)
            if target.version != data["base_version"]:
                error("VERSION_CONFLICT", "正式依赖版本已变化")
            if KnowledgeDependencyChangeRequest.objects.filter(target_dependency=target, status="pending").exists():
                error("REVIEW_CONFLICT", "此依赖已有待审申请")
        if operation != "delete":
            prerequisite = get_point(data["prerequisite_code"], lock=True)
            dependent = get_point(data["dependent_code"], lock=True)
            _validate_edge(prerequisite, dependent, exclude=target.pk if target else None)
            if operation == "create" and KnowledgeDependencyChangeRequest.objects.filter(
                    prerequisite=prerequisite, dependent=dependent, status="pending", operation="create").exists():
                error("DEPENDENCY_EXISTS", "同向依赖已有待审创建申请")
            proposed = {key: data[key] for key in ("prerequisite_code", "dependent_code", "relation_type")}
            proposed["weight"] = float(data["weight"])
        change = KnowledgeDependencyChangeRequest.objects.create(
            operation=operation, target_dependency=target, original_target_id=target.pk if target else None,
            base_version=data.get("base_version"), prerequisite=prerequisite, dependent=dependent,
            relation_type=data.get("relation_type"), weight=data.get("weight"),
            before=dependency_state(target) if target else None, proposed=proposed, reason=data["reason"], submitted_by=user)
        record_event("dependency_change", change.pk, target.version if target else 0, "submitted", user,
                     change_snapshot(change), request_id)
        return change


def mapping_versions(problem_id):
    versions = KnowledgeMappingBatch.objects.filter(problem_id=problem_id).aggregate(
        approved=Max("approved_version"), batch=Max("batch_version"))
    return versions["approved"] or 0, (versions["batch"] or 0) + 1


def _mapping_points(mappings):
    codes = [item["knowledge_code"] for item in mappings]
    if not 1 <= len(mappings) <= 20 or len(set(codes)) != len(codes):
        error("MAPPING_INVALID", "映射必须含 1 至 20 个不重复知识点", 422)
    if sum(item["role"] == "primary" for item in mappings) != 1:
        error("MAPPING_INVALID", "映射必须恰有一个 primary", 422)
    points = {point.code: point for point in KnowledgePoint.objects.select_for_update().filter(code__in=codes)}
    if len(points) != len(codes) or any(point.status != "active" for point in points.values()):
        error("MAPPING_INVALID", "所有映射知识点必须存在且为 active", 422)
    return points


def batch_snapshot(batch):
    return {"snapshot_type": "problem_mapping", "review_batch_id": str(batch.pk), "problem_id": batch.problem_id,
            "batch_version": batch.batch_version, "base_version": batch.base_version,
            "approved_version": batch.approved_version, "status": batch.status, "mappings": batch.payload}


def submit_mapping(user, problem_id, data, request_id):
    require_admin(user)
    with knowledge_write():
        problem = get_problem(user, problem_id, lock=True)
        approved_version, next_batch = mapping_versions(problem.id)
        if data["base_version"] != approved_version:
            error("VERSION_CONFLICT", "当前批准版本已变化")
        if KnowledgeMappingBatch.objects.filter(problem=problem, status="pending").exists():
            error("REVIEW_CONFLICT", "题目已有待审映射批次")
        _mapping_points(data["mappings"])
        payload = [{"knowledge_code": item["knowledge_code"], "role": item["role"], "weight": float(item["weight"]),
                    "source": "manual", "confidence": 1.0} for item in data["mappings"]]
        batch = KnowledgeMappingBatch.objects.create(problem=problem, batch_version=next_batch,
                                                     base_version=approved_version, submitted_by=user, payload=payload)
        record_event("problem_mapping", batch.pk, batch.batch_version, "submitted", user,
                     batch_snapshot(batch), request_id)
        return batch


def get_review(object_type, object_key, lock=False):
    if object_type not in ("dependency_change", "problem_mapping"):
        error("INPUT_INVALID", "非法审核对象类型", 400)
    try:
        key = UUID(str(object_key))
    except (ValueError, TypeError, AttributeError):
        error("INPUT_INVALID", "审核对象标识必须为 UUID", 400)
    model = KnowledgeDependencyChangeRequest if object_type == "dependency_change" else KnowledgeMappingBatch
    queryset = model.objects.select_related("submitted_by", "reviewed_by")
    if object_type == "problem_mapping":
        queryset = queryset.select_related("problem")
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    try:
        return queryset.get(pk=key)
    except model.DoesNotExist:
        error("NOT_FOUND", "审核对象不存在", 404)


def review_capabilities(obj, user):
    if obj.status == "pending" and obj.submitted_by_id != user.pk and user.admin_type == AdminType.SUPER_ADMIN:
        return ["approve", "reject"]
    return []


def review(user, object_type, object_key, data, approve, request_id):
    require_admin(user, super_only=True)
    with knowledge_write():
        obj = get_review(object_type, object_key, lock=True)
        if obj.submitted_by_id == user.pk:
            error("SELF_REVIEW_FORBIDDEN", "提交人不能审核自己的申请", 403)
        if obj.status != "pending":
            error("REVIEW_CONFLICT", "审核对象已经处理")
        if obj.updated_time != data["expected_updated_time"]:
            error("VERSION_CONFLICT", "审核对象版本已变化")
        if object_type == "dependency_change":
            version = _review_dependency(obj, user, approve)
            snapshot = change_snapshot(obj)
        else:
            _review_mapping(obj, user, approve, request_id)
            version = obj.batch_version
            snapshot = batch_snapshot(obj)
        obj.status = "approved" if approve else "rejected"
        obj.reviewed_by = user
        if object_type == "dependency_change":
            obj.review_reason = "" if approve else data["reason"]
        else:
            obj.reason = "" if approve else data["reason"]
        obj.save()
        snapshot["status"] = obj.status
        record_event(object_type, obj.pk, version, "approved" if approve else "rejected", user,
                     snapshot, request_id, "" if approve else data["reason"])
        return obj


def _review_dependency(change, user, approve):
    version = change.base_version or 0
    if not approve:
        return version
    target = None
    if change.operation != "create":
        if not change.target_dependency_id:
            error("VERSION_CONFLICT", "目标依赖已删除")
        target = get_dependency(change.target_dependency_id, lock=True)
        if target.version != change.base_version:
            error("VERSION_CONFLICT", "正式依赖版本已变化")
    if change.operation == "delete":
        version = target.version
        target.delete()
        change.target_dependency_id = None
        return version
    prerequisite = get_point(change.proposed["prerequisite_code"], lock=True)
    dependent = get_point(change.proposed["dependent_code"], lock=True)
    _validate_edge(prerequisite, dependent, exclude=target.pk if target else None)
    fields = dict(prerequisite=prerequisite, dependent=dependent, relation_type=change.proposed["relation_type"],
                  weight=Decimal(str(change.proposed["weight"])))
    if target is None:
        target = KnowledgeDependency.objects.create(**fields, created_by=user)
        # A create request has no original target, even after approval.
    else:
        for key, value in fields.items():
            setattr(target, key, value)
        target.version += 1
        target.save()
    return target.version


def _review_mapping(batch, user, approve, request_id):
    if not approve:
        return
    # All callers hold the advisory lock, so row-lock ordering cannot deadlock
    # with submission, deprecation, or another approval.
    get_problem(user, batch.problem_id, lock=True)
    approved_version, _ = mapping_versions(batch.problem_id)
    if batch.base_version != approved_version:
        error("VERSION_CONFLICT", "当前批准版本已变化")
    points = _mapping_points(batch.payload)
    previous = KnowledgeMappingBatch.objects.filter(problem_id=batch.problem_id, status="approved").first()
    if previous:
        previous.status = "superseded"
        previous.save(update_fields=("status", "updated_time"))
        record_event("problem_mapping", previous.pk, previous.batch_version, "replaced", user,
                     batch_snapshot(previous), request_id, "被新批准批次 {} 替换".format(batch.pk))
    ProblemKnowledge.objects.filter(problem_id=batch.problem_id).delete()
    ProblemKnowledge.objects.bulk_create([
        ProblemKnowledge(problem_id=batch.problem_id, knowledge_point=points[item["knowledge_code"]],
                         role=item["role"], weight=Decimal(str(item["weight"])), reviewed_by=user)
        for item in batch.payload
    ])
    batch.approved_version = approved_version + 1

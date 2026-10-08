import uuid

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils.dateparse import parse_datetime

from .api import (KnowledgeAPIView, KnowledgeError, category, integer,
                  page_params, require_admin, require_super, text)
from .models import (KnowledgeDependency, KnowledgeDependencyChangeRequest,
                     KnowledgeMappingBatch, KnowledgePoint, KnowledgeReviewEvent,
                     ProblemKnowledge)
from .public import graph_data
from .services import (approved_version, audit, create_dependency_request,
                       dependency_proposal, dependency_state, parse_expected, permitted_problem, point_fields,
                       point_referenced, review_dependency, review_mapping,
                       submit_mapping)


def point_data(point):
    return {"id": point.id, "code": point.code, "name": point.name, "normalized_name": point.normalized_name,
            "description": point.description, "category": point.category, "level": point.level, "status": point.status,
            "version": point.version, "aliases": point.aliases, "metadata": point.metadata,
            "created_time": point.created_time.isoformat(), "updated_time": point.updated_time.isoformat()}


def user_data(user):
    return {"id": user.id, "username": user.username} if user else None


def dependency_data(edge):
    if not edge:
        return None
    return {"id": edge.id, "prerequisite": point_data(edge.prerequisite), "dependent": point_data(edge.dependent),
            "relation_type": edge.relation_type, "weight": float(edge.weight), "source": edge.source,
            "confidence": float(edge.confidence), "version": edge.version, "updated_time": edge.updated_time.isoformat()}


def dependency_request_data(change):
    first_event = KnowledgeReviewEvent.objects.filter(object_type="dependency_change", object_key=str(change.id), action="submitted").first()
    state = first_event.snapshot.get("before") if first_event else dependency_state(change.target_dependency)
    before = None
    if state:
        prerequisite = KnowledgePoint.objects.get(code=state["prerequisite_code"])
        dependent = KnowledgePoint.objects.get(code=state["dependent_code"])
        before = {"id": first_event.snapshot["target_dependency_id"] if first_event else change.target_dependency_id,
                  "prerequisite": point_data(prerequisite), "dependent": point_data(dependent),
                  "relation_type": state["relation_type"], "weight": state["weight"], "source": state["source"],
                  "confidence": state["confidence"], "version": state["version"], "updated_time": state["updated_time"]}
    return {"request_id": str(change.id), "operation": change.operation, "target_dependency_id": change.target_dependency_id or
            (first_event.snapshot.get("target_dependency_id") if first_event else None), "base_version": change.base_version,
            "before": before, "proposed": dependency_proposal(change), "status": change.status, "reason": change.reason,
            "review_reason": change.review_reason or None, "submitted_by": user_data(change.submitted_by),
            "reviewed_by": user_data(change.reviewed_by), "created_time": change.created_time.isoformat(),
            "updated_time": change.updated_time.isoformat()}


def mapping_batch_data(batch):
    if not batch:
        return None
    return {"review_batch_id": str(batch.id), "problem_id": batch.problem_id, "batch_version": batch.batch_version,
            "base_version": batch.base_version, "approved_version": batch.approved_version, "status": batch.status,
            "mappings": batch.payload["mappings"], "reason": batch.reason or None, "updated_time": batch.updated_time.isoformat()}


def mapping_set_data(problem, user):
    batches = KnowledgeMappingBatch.objects.filter(problem=problem)
    pending = batches.filter(status="pending").first()
    rows = ProblemKnowledge.objects.filter(problem=problem).select_related("knowledge_point").order_by("knowledge_point__code")
    mappings = [{"id": row.id, "knowledge_code": row.knowledge_point.code, "knowledge_name": row.knowledge_point.name,
                 "role": row.role, "weight": float(row.weight), "review_status": row.review_status,
                 "updated_time": row.updated_time.isoformat()} for row in rows]
    version = approved_version(problem)
    capabilities = ["view"]
    if not pending:
        capabilities.append("submit")
    if mappings:
        capabilities.append("replace_approved")
    if pending and user.is_super_admin() and pending.submitted_by_id != user.id:
        capabilities.extend(["approve", "reject"])
    return {"problem_id": problem.id, "coverage_status": "ready" if mappings else "in_review" if pending else "unannotated",
            "approved_version": version, "next_batch_version": (batches.aggregate(value=Max("batch_version"))["value"] or 0) + 1,
            "mappings": mappings, "pending_batch": mapping_batch_data(pending), "capabilities": capabilities}


def point_capabilities(point, user):
    caps = ["view"]
    if user.is_super_admin():
        caps.extend(["edit", "request_dependency_change"])
        if point.status in {"draft", "active"}:
            caps.append("change_status")
        if point.status == "draft" and not point_referenced(point):
            caps.append("delete_draft")
    return caps


class AdminPointList(KnowledgeAPIView):
    def get(self, request):
        require_admin(request.user)
        query = self.query(request, {"keyword", "category", "level", "status", "page", "page_size"})
        page, size = page_params(query)
        selected_category = category(query.get("category"))
        selected_level = integer(query.get("level"), 1, 5)
        status = query.get("status")
        if status and status not in {"draft", "active", "deprecated"}:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        keyword = query.get("keyword", "")
        if len(keyword) > 128:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        points = KnowledgePoint.objects.all()
        if selected_category:
            points = points.filter(category=selected_category)
        if selected_level:
            points = points.filter(level=selected_level)
        if status:
            points = points.filter(status=status)
        if keyword:
            aliases = [point.id for point in points.only("id", "aliases") if any(keyword.casefold() in alias.casefold() for alias in point.aliases)]
            points = points.filter(Q(code__icontains=keyword) | Q(name__icontains=keyword) | Q(normalized_name__icontains=keyword) | Q(id__in=aliases))
        total = points.count()
        rows = list(points.order_by("-updated_time", "code")[(page - 1) * size:page * size])
        ids = [point.id for point in rows]
        incoming = dict(KnowledgeDependency.objects.filter(dependent_id__in=ids).values("dependent_id").annotate(n=Count("id")).values_list("dependent_id", "n"))
        outgoing = dict(KnowledgeDependency.objects.filter(prerequisite_id__in=ids).values("prerequisite_id").annotate(n=Count("id")).values_list("prerequisite_id", "n"))
        related = dict(ProblemKnowledge.objects.filter(knowledge_point_id__in=ids).values("knowledge_point_id").annotate(n=Count("id")).values_list("knowledge_point_id", "n"))
        items = [{"code": point.code, "name": point.name, "category": point.category, "level": point.level,
                  "status": point.status, "version": point.version, "prerequisite_count": incoming.get(point.id, 0),
                  "dependent_count": outgoing.get(point.id, 0), "related_problem_count": related.get(point.id, 0),
                  "updated_time": point.updated_time.isoformat()} for point in rows]
        return self.reply({"items": items, "page": page, "page_size": size, "total": total})

    def post(self, request):
        require_super(request.user)
        data = self.body(request, {"code", "name", "description", "category", "level", "aliases", "metadata"},
                         {"code", "name", "description", "category", "level"})
        fields = point_fields(data, creating=True)
        try:
            with transaction.atomic():
                point = KnowledgePoint.objects.create(**fields, created_by=request.user)
        except IntegrityError:
            if KnowledgePoint.objects.filter(code=fields["code"]).exists():
                raise KnowledgeError("KNOWLEDGE_CODE_CONFLICT", 409)
            raise KnowledgeError("KNOWLEDGE_NAME_CONFLICT", 409)
        return self.reply(point_data(point), 201)


class AdminPointDetail(KnowledgeAPIView):
    def _point(self, code_value):
        try:
            return KnowledgePoint.objects.get(code=code_value)
        except KnowledgePoint.DoesNotExist:
            raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)

    def get(self, request, knowledge_code):
        require_admin(request.user)
        self.query(request, set())
        point = self._point(knowledge_code)
        prerequisites = KnowledgeDependency.objects.filter(dependent=point).select_related("prerequisite").order_by("prerequisite__code")
        dependents = KnowledgeDependency.objects.filter(prerequisite=point).select_related("dependent").order_by("dependent__code")
        related = ProblemKnowledge.objects.filter(knowledge_point=point, problem__contest__isnull=True).select_related("problem").order_by("problem___id", "problem_id")
        if not request.user.is_super_admin() and request.user.problem_permission == "Own":
            related = related.filter(problem__created_by=request.user)

        def dep_summary(edge, other):
            return {"dependency_id": edge.id, "code": other.code, "name": other.name,
                    "relation_type": edge.relation_type, "weight": float(edge.weight), "version": edge.version}
        related_items = [{"problem_id": row.problem_id, "display_id": row.problem._id, "title": row.problem.title,
                          "role": row.role, "weight": float(row.weight)} for row in related[:100]]
        return self.reply({"knowledge_point": point_data(point), "capabilities": point_capabilities(point, request.user),
                           "prerequisites": {"items": [dep_summary(edge, edge.prerequisite) for edge in prerequisites[:100]], "total": prerequisites.count()},
                           "dependents": {"items": [dep_summary(edge, edge.dependent) for edge in dependents[:100]], "total": dependents.count()},
                           "related_problems": {"items": related_items, "total": related.count()}})

    def patch(self, request, knowledge_code):
        require_super(request.user)
        data = self.body(request, {"version", "name", "description", "category", "level", "status", "aliases", "metadata"}, {"version"})
        if len(data) < 2:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        version = integer(data["version"], 1, 2147483647)
        fields = point_fields({key: value for key, value in data.items() if key not in {"version", "status"}})
        try:
            with transaction.atomic():
                point = KnowledgePoint.objects.select_for_update().get(code=knowledge_code)
                if point.version != version:
                    raise KnowledgeError("KNOWLEDGE_VERSION_CONFLICT", 409)
                if "status" in data:
                    wanted = data["status"]
                    if wanted != point.status and (point.status, wanted) not in {("draft", "active"), ("active", "deprecated")}:
                        raise KnowledgeError("KNOWLEDGE_STATE_CONFLICT", 409)
                    if wanted == "deprecated" and point_referenced(point, pending_only=True):
                        raise KnowledgeError("KNOWLEDGE_STATE_CONFLICT", 409)
                    fields["status"] = wanted
                for key, value in fields.items():
                    setattr(point, key, value)
                point.version += 1
                point.save()
        except KnowledgePoint.DoesNotExist:
            raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)
        except IntegrityError:
            raise KnowledgeError("KNOWLEDGE_NAME_CONFLICT", 409)
        return self.reply(point_data(point))


class AdminPointDelete(KnowledgeAPIView):
    def post(self, request, knowledge_code):
        require_super(request.user)
        data = self.body(request, {"version", "reason"}, {"version", "reason"})
        version = integer(data["version"], 1, 2147483647)
        reason = text(data["reason"], 2, 500)
        with transaction.atomic():
            try:
                point = KnowledgePoint.objects.select_for_update().get(code=knowledge_code)
            except KnowledgePoint.DoesNotExist:
                raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)
            if point.status != "draft" or point.version != version or point_referenced(point):
                raise KnowledgeError("KNOWLEDGE_STATE_CONFLICT", 409)
            snapshot = {"snapshot_type": "knowledge_point", "before": {key: getattr(point, key) for key in
                        ("code", "name", "category", "level", "status", "version")}, "after": None}
            audit("knowledge_point", point.code, point.version, "deleted", request.user, snapshot, self.request_id, reason)
            point.delete()
        from django.http import HttpResponse
        response = HttpResponse(status=204)
        response["X-API-Version"] = "0.9.9"
        return response


class AdminGraph(KnowledgeAPIView):
    def get(self, request):
        require_admin(request.user)
        return self.reply(graph_data(self.query(request, {"root_code", "depth", "category", "level"}), admin=True))


class AdminDependencyRequest(KnowledgeAPIView):
    def post(self, request):
        require_super(request.user)
        data = self.body(request, {"operation", "reason", "target_dependency_id", "base_version", "prerequisite_code",
                                   "dependent_code", "relation_type", "weight"}, {"operation", "reason"})
        change = create_dependency_request(data, request.user, self.request_id)
        return self.reply(dependency_request_data(change), 201)


class AdminMapping(KnowledgeAPIView):
    def get(self, request, problem_id):
        require_admin(request.user)
        self.query(request, set())
        return self.reply(mapping_set_data(permitted_problem(problem_id, request.user), request.user))

    def put(self, request, problem_id):
        require_admin(request.user)
        problem = permitted_problem(problem_id, request.user)
        data = self.body(request, {"base_version", "mappings"}, {"base_version", "mappings"})
        batch = submit_mapping(problem, data, request.user, self.request_id)
        return self.reply(mapping_batch_data(batch), 201)


def review_object(object_type, object_key, lock=False):
    if object_type not in {"dependency_change", "problem_mapping"}:
        raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)
    try:
        object_id = uuid.UUID(object_key)
    except (ValueError, AttributeError):
        raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)
    model = KnowledgeDependencyChangeRequest if object_type == "dependency_change" else KnowledgeMappingBatch
    query = model.objects.select_for_update() if lock else model.objects
    try:
        return query.select_related("submitted_by", "reviewed_by").get(id=object_id)
    except model.DoesNotExist:
        raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)


def review_item(obj, object_type):
    if object_type == "dependency_change":
        proposal = dependency_proposal(obj)
        label = "{} → {}".format(proposal["prerequisite_code"], proposal["dependent_code"]) if proposal else f"Dependency {obj.target_dependency_id}"
        operation = obj.operation
        version = obj.base_version or 0
        reason = obj.review_reason or None
    else:
        label = obj.problem.title[:256]
        operation = "replace"
        version = obj.batch_version
        reason = obj.reason or None
    return {"object_type": object_type, "object_key": str(obj.id), "object_version": version,
            "operation": operation, "submitter": user_data(obj.submitted_by),
            "target_summary": {"label": label}, "status": obj.status,
            "created_time": obj.created_time.isoformat(), "updated_time": obj.updated_time.isoformat(), "reason": reason}


def review_caps(obj, user):
    return ["approve", "reject"] if obj.status == "pending" and obj.submitted_by_id != user.id else []


class AdminReviewList(KnowledgeAPIView):
    def get(self, request):
        require_super(request.user)
        query = self.query(request, {"object_type", "submitter_id", "status", "updated_from", "updated_to", "keyword", "page", "page_size"})
        page, size = page_params(query)
        object_type = query.get("object_type")
        if object_type and object_type not in {"dependency_change", "problem_mapping"}:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        status = query.get("status")
        if status and status not in {"pending", "approved", "rejected", "superseded"}:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        submitter_id = integer(query.get("submitter_id"), 1, 2147483647)
        keyword = query.get("keyword", "")
        if len(keyword) > 128:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        times = {}
        for name in ("updated_from", "updated_to"):
            if query.get(name):
                parsed = parse_datetime(query[name])
                if parsed is None or parsed.tzinfo is None:
                    raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
                times[name] = parsed
        if times.get("updated_from") and times.get("updated_to") and times["updated_from"] > times["updated_to"]:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        items = []
        for kind, model in (("dependency_change", KnowledgeDependencyChangeRequest), ("problem_mapping", KnowledgeMappingBatch)):
            if object_type and kind != object_type:
                continue
            related = ("submitted_by", "problem") if kind == "problem_mapping" else ("submitted_by", "prerequisite", "dependent")
            rows = model.objects.select_related(*related)
            if submitter_id:
                rows = rows.filter(submitted_by_id=submitter_id)
            if status:
                rows = rows.filter(status=status)
            if times.get("updated_from"):
                rows = rows.filter(updated_time__gte=times["updated_from"])
            if times.get("updated_to"):
                rows = rows.filter(updated_time__lte=times["updated_to"])
            items.extend(review_item(row, kind) for row in rows)
        if keyword:
            lowered = keyword.casefold()
            items = [item for item in items if lowered in item["target_summary"]["label"].casefold() or
                     lowered in item["submitter"]["username"].casefold() or lowered in item["object_key"].casefold()]
        items.sort(key=lambda item: (item["updated_time"], item["object_key"]), reverse=True)
        total = len(items)
        return self.reply({"items": items[(page - 1) * size:page * size], "page": page, "page_size": size, "total": total})


class AdminReviewDetail(KnowledgeAPIView):
    def get(self, request, object_type, object_key):
        require_super(request.user)
        self.query(request, set())
        obj = review_object(object_type, object_key)
        if object_type == "dependency_change":
            data = {"object_type": object_type, "request": dependency_request_data(obj), "capabilities": review_caps(obj, request.user)}
        else:
            data = {"object_type": object_type, "problem": {"problem_id": obj.problem_id, "display_id": obj.problem._id,
                    "title": obj.problem.title}, "current_approved_version": approved_version(obj.problem),
                    "batch": mapping_batch_data(obj), "capabilities": review_caps(obj, request.user)}
        return self.reply(data)


class AdminReviewAction(KnowledgeAPIView):
    def post(self, request, object_type, object_key, action):
        require_super(request.user)
        required = {"expected_updated_time"} | ({"reason"} if action == "reject" else set())
        data = self.body(request, required, required)
        reason = text(data["reason"], 2, 500) if action == "reject" else ""
        try:
            with transaction.atomic():
                obj = review_object(object_type, object_key, lock=True)
                if obj.submitted_by_id == request.user.id:
                    raise KnowledgeError("KNOWLEDGE_SELF_REVIEW_FORBIDDEN", 403)
                parse_expected(data["expected_updated_time"], obj.updated_time)
                if object_type == "dependency_change":
                    list(KnowledgePoint.objects.select_for_update().order_by("id").values_list("id", flat=True))
                    review_dependency(obj, action, request.user, self.request_id, reason)
                else:
                    review_mapping(obj, action, request.user, self.request_id, reason)
                obj.refresh_from_db()
        except IntegrityError:
            raise KnowledgeError("KNOWLEDGE_VERSION_CONFLICT", 409)
        return self.reply(review_item(obj, object_type))

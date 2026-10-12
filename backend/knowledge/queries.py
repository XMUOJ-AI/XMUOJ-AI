"""Read models: no pending/rejected data may enter a public projection."""
from collections import defaultdict, deque
from django.db import transaction
from django.db.models import CharField, Count, OuterRef, Q, Subquery, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce

from account.models import AdminType
from problem.models import Problem

from . import services
from .models import KnowledgeDependency, KnowledgeDependencyChangeRequest, KnowledgeMappingBatch, KnowledgePoint
from .models import ProblemKnowledge
from .serializers import (batch_data, change_data, normalize_name, point_data, problem_summary,
                          user_summary)


def active_edges():
    return KnowledgeDependency.objects.filter(prerequisite__status="active", dependent__status="active")


def point_counts(queryset):
    def count(source, field):
        # Independent indexed aggregates avoid a dependencies × mappings join.
        source = source.filter(**{field: OuterRef("pk")}).order_by().values(field).annotate(total=Count("pk"))
        return Coalesce(Subquery(source.values("total")), Value(0))

    return queryset.annotate(
        prerequisite_count=count(active_edges(), "dependent_id"),
        dependent_count=count(active_edges(), "prerequisite_id"))


def related_problem_counts(point_ids, user):
    out_of_scope = Problem.objects.exclude(services.problem_scope_filter(user)).values("pk")
    mappings = ProblemKnowledge.objects.filter(knowledge_point_id__in=point_ids).order_by()
    # pk_approved_only guarantees all formal rows are approved. COUNT(*) can
    # use the existing knowledge FK index without loading mapping/problem rows.
    totals = mappings.values("knowledge_point_id").annotate(total=Count("*"))
    excluded = mappings.filter(problem_id__in=out_of_scope).values("knowledge_point_id").annotate(total=-Count("*"))
    counts = defaultdict(int)
    # One SQL snapshot prevents replacement between the total and subtraction.
    for row in totals.union(excluded, all=True):
        counts[row["knowledge_point_id"]] += row["total"]
    return counts


def public_point(point):
    return dict({key: getattr(point, key) for key in ("code", "name", "description", "category", "level", "aliases")},
                prerequisite_count=point.prerequisite_count, dependent_count=point.dependent_count)


def admin_list_point(point):
    fields = ("code", "name", "category", "level", "status", "version", "prerequisite_count", "dependent_count",
              "related_problem_count")
    return dict({key: getattr(point, key) for key in fields}, updated_time=point.updated_time.isoformat())


def paginate(queryset, page, page_size, serialize):
    total = queryset.count()
    items = [serialize(item) for item in queryset[(page - 1) * page_size:page * page_size]]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def list_points(user, params, public=False):
    queryset = KnowledgePoint.objects.all()
    if public:
        queryset = queryset.filter(status="active")
    for field in ("category", "level", "status"):
        if field in params:
            queryset = queryset.filter(**{field: params[field]})
    keyword = params.get("keyword", "")
    if keyword:
        queryset = queryset.filter(Q(code__icontains=keyword) | Q(name__icontains=keyword)
                                   | Q(normalized_name__icontains=normalize_name(keyword)) | Q(aliases__icontains=keyword))
    total = queryset.count()
    page, page_size = params["page"], params["page_size"]
    ordering = ("code",) if public else ("-updated_time", "code")
    points = list(point_counts(queryset).order_by(*ordering)[(page-1)*page_size:page*page_size])
    if not public:
        counts = related_problem_counts([point.pk for point in points], user)
        for point in points:
            point.related_problem_count = counts[point.pk]
    serialize = public_point if public else admin_list_point
    return {"items": [serialize(point) for point in points], "page": page, "page_size": page_size, "total": total}


def dependency_summaries(point, direction, public=False):
    if direction == "prerequisites":
        queryset, other = active_edges().filter(dependent=point), "prerequisite"
    else:
        queryset, other = active_edges().filter(prerequisite=point), "dependent"
    queryset = queryset.select_related(other).only(other + "__code", other + "__name", "relation_type", "weight", "version").order_by(other + "__code", "pk")

    def serialize(edge):
        neighbor = getattr(edge, other)
        result = {"code": neighbor.code, "name": neighbor.name,
                  "relation_type": edge.relation_type, "weight": float(edge.weight)}
        if not public:
            result.update(dependency_id=edge.id, version=edge.version)
        return result

    return queryset, serialize


def problem_summaries(point, user, public=False):
    queryset = ProblemKnowledge.objects.filter(knowledge_point=point, review_status="approved",
                                               problem__contest__isnull=True)
    if public:
        queryset = queryset.filter(problem__visible=True)
    else:
        queryset = queryset.filter(problem__in=services.problem_scope(user).values("pk"))
    queryset = queryset.select_related("problem").only("problem_id", "role", "weight", "problem___id", "problem__title").order_by("problem___id", "problem_id")

    def serialize(mapping):
        result = {"display_id": mapping.problem._id, "title": mapping.problem.title}
        if not public:
            result.update(problem_id=mapping.problem_id, role=mapping.role, weight=float(mapping.weight))
        return result

    return queryset, serialize


def detail(user, code, public=False, include_collections=True):
    point = services.get_point(code, active=public)
    if public and not include_collections:
        # Explicit opt-out keeps the legacy array types without pretending an
        # empty array is the complete collection. Counts remain authoritative.
        point = point_counts(KnowledgePoint.objects.filter(pk=point.pk)).get()
        return dict(public_point(point), prerequisites=[], dependents=[], related_problems=[])
    collections = {}
    for direction in ("prerequisites", "dependents"):
        queryset, serialize = dependency_summaries(point, direction, public)
        collections[direction] = ([serialize(item) for item in queryset[:101]] if public
                                  else {"items": [serialize(item) for item in queryset[:100]], "total": queryset.count()})
    queryset, serialize = problem_summaries(point, user, public)
    collections["related_problems"] = ([serialize(item) for item in queryset[:101]] if public
                                       else {"items": [serialize(item) for item in queryset[:100]], "total": queryset.count()})
    if public:
        oversized = [name for name, items in collections.items() if len(items) > 100]
        if oversized:
            base = "/api/knowledge-points/" + point.code
            endpoints = {name: base + ("/related-problems" if name == "related_problems" else "/dependencies?direction=" + name)
                         for name in oversized}
            services.error("PAGINATION_REQUIRED", "集合超过详情内嵌上限，请使用公开分页接口", 409,
                           {"collection_limit": 100, "collections": oversized, "endpoints": endpoints,
                            "detail_url": base + "?include_collections=false"})
        point.prerequisite_count = len(collections["prerequisites"])
        point.dependent_count = len(collections["dependents"])
        return dict(public_point(point), **collections)
    capabilities = ["view"]
    if user.admin_type == AdminType.SUPER_ADMIN:
        capabilities += ["edit", "request_dependency_change"]
        if point.status in ("draft", "active"):
            capabilities.append("change_status")
        if point.status == "draft" and not services.has_references(point):
            capabilities.append("delete_draft")
    return dict(knowledge_point=point_data(point), capabilities=capabilities, **collections)


def graph(params, public=False):
    points = {point.code: point for point in KnowledgePoint.objects.filter(status="active")}
    edges = list(active_edges().values("id", "prerequisite__code", "dependent__code", "relation_type", "weight", "version"))
    root = params.get("root_code")
    if root:
        if root not in points:
            services.error("NOT_FOUND", "知识点不存在", 404)
        adjacency = defaultdict(list)
        for edge in edges:
            source, target = edge["prerequisite__code"], edge["dependent__code"]
            adjacency[source].append(target)
            adjacency[target].append(source)
        distances, queue = {root: 0}, deque([root])
        while queue:
            code = queue.popleft()
            if distances[code] == params["depth"]:
                continue
            for neighbor in adjacency[code]:
                if neighbor not in distances:
                    distances[neighbor] = distances[code] + 1
                    queue.append(neighbor)
    else:
        distances = dict.fromkeys(points, 0)
    candidates = [code for code in distances if code == root or all(
        key not in params or getattr(points[code], key) == params[key] for key in ("category", "level"))]
    candidates.sort(key=lambda code: (distances[code], code))
    selected = set(candidates[:500])
    nodes = [{"code": code, "name": points[code].name, "level": points[code].level,
              "category": points[code].category} for code in candidates[:500]]
    result_edges = []
    for edge in edges:
        source, target = edge["prerequisite__code"], edge["dependent__code"]
        if source in selected and target in selected:
            item = {"from": source, "to": target, "relation_type": edge["relation_type"], "weight": float(edge["weight"])}
            if not public:
                item.update(id=edge["id"], version=edge["version"])
            result_edges.append(item)
    result_edges.sort(key=lambda edge: (edge["from"], edge["to"]))
    return {"nodes": nodes, "edges": result_edges, "truncated": len(candidates) > 500}


@transaction.atomic
def mapping_set(user, problem_id):
    # Keep versions, pending state and current rows from the same replacement.
    # Writers lock this problem before replacing rows; readers never take the
    # advisory lock later, so this narrower read lock cannot invert lock order.
    problem = services.get_problem(user, problem_id, lock=True)
    approved_version, next_batch = services.mapping_versions(problem_id)
    mappings = list(ProblemKnowledge.objects.filter(problem=problem, review_status="approved")
                    .select_related("knowledge_point").order_by("knowledge_point__code"))
    pending = KnowledgeMappingBatch.objects.filter(problem=problem, status="pending").first()
    capabilities = ["view"]
    if pending:
        capabilities += services.review_capabilities(pending, user)
    else:
        capabilities += ["submit"]
        if mappings:
            capabilities += ["replace_approved"]
    return {"problem_id": problem_id, "problem": problem_summary(problem), "approved_version": approved_version,
            "next_batch_version": next_batch, "coverage_status": "ready" if mappings else "in_review" if pending else "unannotated",
            "mappings": [{"id": item.pk, "knowledge_code": item.knowledge_point.code,
                          "knowledge_name": item.knowledge_point.name, "role": item.role, "weight": float(item.weight),
                          "review_status": item.review_status, "updated_time": item.updated_time.isoformat()} for item in mappings],
            "pending_batch": batch_data(pending) if pending else None, "capabilities": capabilities}


def review_item(obj):
    dependency = isinstance(obj, KnowledgeDependencyChangeRequest)
    if dependency:
        state = obj.proposed or obj.before
        target = {"label": state["prerequisite_code"] + " → " + state["dependent_code"]}
        version = obj.base_version or 0
        # Immutable event version remains available after deletion/replacement.
        if obj.status == "approved" and obj.operation != "delete":
            version += 1
    else:
        target = {"label": obj.problem._id, "secondary_label": obj.problem.title[:256]}
        version = obj.batch_version
    return {"object_type": "dependency_change" if dependency else "problem_mapping", "object_key": str(obj.pk),
            "object_version": version, "operation": obj.operation if dependency else "replace",
            "submitter": user_summary(obj.submitted_by), "target_summary": target,
            "status": obj.status, "created_time": obj.created_time.isoformat(), "updated_time": obj.updated_time.isoformat(),
            "reason": (obj.review_reason or obj.reason) if dependency else obj.reason}


def review_detail(obj, user):
    capabilities = services.review_capabilities(obj, user)
    if isinstance(obj, KnowledgeDependencyChangeRequest):
        return {"object_type": "dependency_change", "request": change_data(obj), "capabilities": capabilities}
    approved_version, _ = services.mapping_versions(obj.problem_id)
    return {"object_type": "problem_mapping", "problem": problem_summary(obj.problem),
            "current_approved_version": approved_version, "batch": batch_data(obj), "capabilities": capabilities}


def review_queue(params):
    # Paginate the combined queue in SQL, then load only those selected objects.
    sources, index = {}, None
    types = [params["object_type"]] if "object_type" in params else ["dependency_change", "problem_mapping"]
    for object_type in types:
        dependency = object_type == "dependency_change"
        model = KnowledgeDependencyChangeRequest if dependency else KnowledgeMappingBatch
        queryset = model.objects.select_related("submitted_by")
        if not dependency:
            queryset = queryset.select_related("problem").defer("payload")
        sources[object_type] = queryset
        queryset = queryset.filter(status=params.get("status", "pending"))
        for parameter, field in (("submitter_id", "submitted_by_id"), ("updated_from", "updated_time__gte"),
                                 ("updated_to", "updated_time__lte")):
            if parameter in params:
                queryset = queryset.filter(**{field: params[parameter]})
        keyword = params.get("keyword")
        if keyword:
            predicate = Q(submitted_by__username__icontains=keyword)
            if dependency:
                codes = KnowledgePoint.objects.filter(Q(code__icontains=keyword) | Q(name__icontains=keyword)).values("code")
                queryset = queryset.annotate(before_prerequisite=KeyTextTransform("prerequisite_code", "before"),
                                             before_dependent=KeyTextTransform("dependent_code", "before"))
                predicate |= (Q(prerequisite__code__in=codes) | Q(dependent__code__in=codes)
                              | Q(before_prerequisite__in=codes) | Q(before_dependent__in=codes))
            else:
                predicate |= Q(problem___id__icontains=keyword) | Q(problem__title__icontains=keyword)
            queryset = queryset.filter(predicate)
        source_index = queryset.order_by().annotate(queue_type=Value(object_type), queue_key=Cast("pk", CharField()))
        source_index = source_index.values("queue_type", "queue_key", "created_time")
        index = source_index if index is None else index.union(source_index, all=True)
    start = (params["page"] - 1) * params["page_size"]
    total = index.count()
    page = list(index.order_by("created_time", "queue_key")[start:start + params["page_size"]])
    objects = {}
    for object_type, queryset in sources.items():
        # A review may finish after page selection; hydrate the selected IDs regardless of their new status.
        keys = [item["queue_key"] for item in page if item["queue_type"] == object_type]
        if keys:
            objects.update({str(obj.pk): review_item(obj) for obj in queryset.filter(pk__in=keys)})
    return {"items": [objects[item["queue_key"]] for item in page], "page": params["page"],
            "page_size": params["page_size"], "total": total}

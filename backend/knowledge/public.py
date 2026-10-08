from collections import deque

from django.db.models import Q

from problem.models import Problem

from .api import KnowledgeAPIView, KnowledgeError, category, code, integer, page_params
from .models import KnowledgeDependency, KnowledgePoint, ProblemKnowledge


def public_point(point):
    return {key: getattr(point, key) for key in ("code", "name", "description", "category", "level", "aliases")}


def graph_data(query, admin=False):
    root_code = query.get("root_code")
    if root_code is not None:
        code(root_code)
    depth = integer(query.get("depth"), 1, 8, 3)
    selected_category = category(query.get("category"))
    selected_level = integer(query.get("level"), 1, 5)
    points = list(KnowledgePoint.objects.filter(status="active"))
    by_code = {point.code: point for point in points}
    if root_code and root_code not in by_code:
        raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)
    point_ids = [point.id for point in points]
    edges = list(KnowledgeDependency.objects.filter(prerequisite_id__in=point_ids, dependent_id__in=point_ids)
                 .select_related("prerequisite", "dependent"))
    distances = {root_code: 0} if root_code else {}
    if root_code:
        neighbors = {}
        for edge in edges:
            neighbors.setdefault(edge.prerequisite.code, set()).add(edge.dependent.code)
            neighbors.setdefault(edge.dependent.code, set()).add(edge.prerequisite.code)
        queue = deque([root_code])
        while queue:
            current = queue.popleft()
            if distances[current] >= depth:
                continue
            for neighbor in sorted(neighbors.get(current, ())):
                if neighbor not in distances:
                    distances[neighbor] = distances[current] + 1
                    queue.append(neighbor)
    candidates = [point for point in points if (not root_code or point.code in distances) and
                  (point.code == root_code or (not selected_category or point.category == selected_category) and
                   (not selected_level or point.level == selected_level))]
    candidates.sort(key=lambda point: (distances.get(point.code, 0), point.code))
    chosen = candidates[:500]
    chosen_codes = {point.code for point in chosen}
    visible_edges = sorted((edge for edge in edges if edge.prerequisite.code in chosen_codes and edge.dependent.code in chosen_codes),
                           key=lambda edge: (edge.prerequisite.code, edge.dependent.code))

    def edge_data(edge):
        item = {"from": edge.prerequisite.code, "to": edge.dependent.code,
                "relation_type": edge.relation_type, "weight": float(edge.weight)}
        if admin:
            item["id"] = edge.id
        return item
    return {
        "nodes": [{"code": point.code, "name": point.name, "level": point.level} for point in chosen],
        "edges": [edge_data(edge) for edge in visible_edges],
        "truncated": len(candidates) > 500,
    }


class PublicPointList(KnowledgeAPIView):
    def get(self, request):
        query = self.query(request, {"keyword", "category", "level", "page", "page_size"})
        page, size = page_params(query)
        selected_category = category(query.get("category"))
        selected_level = integer(query.get("level"), 1, 5)
        keyword = query.get("keyword", "")
        if len(keyword) > 128:
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400)
        points = KnowledgePoint.objects.filter(status="active")
        if selected_category:
            points = points.filter(category=selected_category)
        if selected_level:
            points = points.filter(level=selected_level)
        if keyword:
            matched_alias_ids = [point.id for point in points.only("id", "aliases") if any(keyword.casefold() in alias.casefold() for alias in point.aliases)]
            points = points.filter(Q(code__icontains=keyword) | Q(name__icontains=keyword) | Q(normalized_name__icontains=keyword) | Q(id__in=matched_alias_ids))
        total = points.count()
        rows = points.order_by("code")[(page - 1) * size:page * size]
        return self.reply({"items": [public_point(point) for point in rows], "page": page, "page_size": size, "total": total})


class PublicPointDetail(KnowledgeAPIView):
    def get(self, request, knowledge_code):
        self.query(request, set())
        try:
            point = KnowledgePoint.objects.get(code=knowledge_code, status="active")
        except KnowledgePoint.DoesNotExist:
            raise KnowledgeError("KNOWLEDGE_NOT_FOUND", 404)
        prerequisites = KnowledgeDependency.objects.filter(dependent=point, prerequisite__status="active").select_related("prerequisite").order_by("prerequisite__code")
        dependents = KnowledgeDependency.objects.filter(prerequisite=point, dependent__status="active").select_related("dependent").order_by("dependent__code")

        def summary(edge, other):
            return {"code": other.code, "name": other.name, "relation_type": edge.relation_type, "weight": float(edge.weight)}
        related_ids = ProblemKnowledge.objects.filter(knowledge_point=point, review_status="approved").values_list("problem_id", flat=True)
        related = Problem.objects.filter(id__in=related_ids, contest__isnull=True, visible=True).order_by("_id", "id")
        return self.reply({**public_point(point),
                           "prerequisites": [summary(edge, edge.prerequisite) for edge in prerequisites],
                           "dependents": [summary(edge, edge.dependent) for edge in dependents],
                           "related_problems": [{"display_id": problem._id, "title": problem.title} for problem in related]})


class PublicGraph(KnowledgeAPIView):
    def get(self, request):
        return self.reply(graph_data(self.query(request, {"root_code", "depth", "category", "level"})))

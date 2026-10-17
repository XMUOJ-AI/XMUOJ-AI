import re

from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware

from utils.contract_api import ContractAPIView

from . import queries, services
from .models import CATEGORIES
from .serializers import (DeleteInput, DependencyChangeInput, KnowledgeCreateInput, KnowledgeUpdateInput,
                          MappingSetInput, RejectInput, ReviewInput, batch_data, change_data, dependency_data, point_data)


def error_codes(errors):
    if isinstance(errors, dict):
        errors = list(errors.values())
    if isinstance(errors, list):
        return set().union(*map(error_codes, errors))
    return {getattr(errors, "code", None)}


class KnowledgeAPIView(ContractAPIView):
    contract_version = "0.9.9"
    error_prefix = "KNOWLEDGE"

    def input(self, serializer_class):
        serializer = serializer_class(data=self.request.data)
        if not serializer.is_valid():
            if error_codes(serializer.errors) == {"weight_range"}:
                services.error("WEIGHT_INVALID", "权重必须大于 0 且不超过 1", 422, serializer.errors)
            services.error("INPUT_INVALID", "请求字段不合法", 400, serializer.errors)
        return serializer.validated_data

    def params(self, allowed, pagination=False):
        raw = self.request.query_params
        if set(raw) - set(allowed) or any(len(raw.getlist(key)) != 1 for key in raw):
            services.error("INPUT_INVALID", "不支持的或重复的查询参数", 400)
        result = dict(raw.items())
        integers = {"page": (1, None), "page_size": (1, 100), "level": (1, 5), "depth": (1, 8), "submitter_id": (1, None)}
        for key, (minimum, maximum) in integers.items():
            if key in result:
                value = result[key]
                if not re.fullmatch(r"[0-9]{1,12}", value):
                    services.error("INPUT_INVALID", "分页或层级参数非法", 400)
                result[key] = int(value)
                if result[key] < minimum or (maximum is not None and result[key] > maximum):
                    services.error("INPUT_INVALID", "查询参数超出范围", 400)
        enums = {"category": CATEGORIES, "status": ("draft", "active", "deprecated") if "submitter_id" not in allowed
                 else ("pending", "approved", "rejected", "superseded"),
                 "direction": ("prerequisites", "dependents"), "object_type": ("dependency_change", "problem_mapping")}
        for key, choices in enums.items():
            if key in result and result[key] not in choices:
                services.error("INPUT_INVALID", "查询参数枚举非法", 400)
        if len(result.get("keyword", "")) > 128:
            services.error("INPUT_INVALID", "关键词过长", 400)
        if "root_code" in result and not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", result["root_code"]):
            services.error("INPUT_INVALID", "知识点 code 非法", 400)
        for key in ("updated_from", "updated_to"):
            if key in result:
                try:
                    value = parse_datetime(result[key])
                except (ValueError, TypeError):
                    value = None
                if value is None or not is_aware(value):
                    services.error("INPUT_INVALID", "时间参数必须包含 ISO 8601 时区", 400)
                result[key] = value
        if "updated_from" in result and "updated_to" in result and result["updated_from"] > result["updated_to"]:
            services.error("INPUT_INVALID", "开始时间不得晚于结束时间", 400)
        if pagination:
            result.setdefault("page", 1)
            result.setdefault("page_size", 20)
        return result

    @property
    def audit_request_id(self):
        return self.request_id


class PublicKnowledgeList(KnowledgeAPIView):
    def get(self, request):
        params = self.params(("page", "page_size", "keyword", "category", "level"), pagination=True)
        return self.success(queries.list_points(request.user, params, public=True))


class PublicKnowledgeDetail(KnowledgeAPIView):
    def get(self, request, knowledge_code):
        params = self.params(("include_collections",))
        include = params.get("include_collections", "true")
        if include not in ("true", "false"):
            services.error("INPUT_INVALID", "include_collections 必须为 true 或 false", 400)
        return self.success(queries.detail(request.user, knowledge_code, public=True, include_collections=include == "true"))


class PublicDependencySummaries(KnowledgeAPIView):
    def get(self, request, knowledge_code):
        params = self.params(("direction", "page", "page_size"), pagination=True)
        queryset, serialize = queries.dependency_summaries(
            services.get_point(knowledge_code, active=True), params.get("direction", "prerequisites"), public=True)
        return self.success(queries.paginate(queryset, params["page"], params["page_size"], serialize))


class PublicProblemSummaries(KnowledgeAPIView):
    def get(self, request, knowledge_code):
        params = self.params(("page", "page_size"), pagination=True)
        queryset, serialize = queries.problem_summaries(services.get_point(knowledge_code, active=True), request.user, public=True)
        return self.success(queries.paginate(queryset, params["page"], params["page_size"], serialize))


class PublicKnowledgeGraph(KnowledgeAPIView):
    def get(self, request):
        params = self.params(("root_code", "depth", "category", "level"))
        params.setdefault("depth", 3)
        return self.success(queries.graph(params, public=True))


class AdminKnowledgeList(KnowledgeAPIView):
    def get(self, request):
        services.require_admin(request.user)
        params = self.params(("page", "page_size", "keyword", "category", "level", "status"), pagination=True)
        return self.success(queries.list_points(request.user, params))

    def post(self, request):
        services.require_admin(request.user, super_only=True)
        return self.success(point_data(services.create_point(request.user, self.input(KnowledgeCreateInput))), status=201)


class AdminKnowledgeDetail(KnowledgeAPIView):
    def get(self, request, knowledge_code):
        services.require_admin(request.user)
        self.params(())
        return self.success(queries.detail(request.user, knowledge_code))

    def patch(self, request, knowledge_code):
        services.require_admin(request.user, super_only=True)
        point = services.update_point(request.user, knowledge_code, self.input(KnowledgeUpdateInput))
        return self.success(point_data(point))


class AdminKnowledgeDelete(KnowledgeAPIView):
    def post(self, request, knowledge_code):
        services.require_admin(request.user, super_only=True)
        services.delete_point(request.user, knowledge_code, self.input(DeleteInput), self.audit_request_id)
        return self.success(None, status=204)


class AdminKnowledgeGraph(KnowledgeAPIView):
    def get(self, request):
        services.require_admin(request.user)
        params = self.params(("root_code", "depth", "category", "level"))
        params.setdefault("depth", 3)
        return self.success(queries.graph(params))


class AdminDependencyDetail(KnowledgeAPIView):
    def get(self, request, dependency_id):
        services.require_admin(request.user)
        self.params(())
        return self.success(dependency_data(services.get_dependency(dependency_id)))


class AdminDependencySummaries(KnowledgeAPIView):
    def get(self, request, knowledge_code):
        services.require_admin(request.user)
        params = self.params(("direction", "page", "page_size"), pagination=True)
        queryset, serialize = queries.dependency_summaries(services.get_point(knowledge_code), params.get("direction", "prerequisites"))
        return self.success(queries.paginate(queryset, params["page"], params["page_size"], serialize))


class AdminProblemSummaries(KnowledgeAPIView):
    def get(self, request, knowledge_code):
        services.require_admin(request.user)
        params = self.params(("page", "page_size"), pagination=True)
        queryset, serialize = queries.problem_summaries(services.get_point(knowledge_code), request.user)
        return self.success(queries.paginate(queryset, params["page"], params["page_size"], serialize))


class DependencyChangeCreate(KnowledgeAPIView):
    def post(self, request):
        services.require_admin(request.user, super_only=True)
        change = services.submit_dependency(request.user, self.input(DependencyChangeInput), self.audit_request_id)
        return self.success(change_data(change), status=201)


class ProblemMappings(KnowledgeAPIView):
    def get(self, request, problem_id):
        services.require_admin(request.user)
        self.params(())
        return self.success(queries.mapping_set(request.user, problem_id))

    def put(self, request, problem_id):
        services.require_admin(request.user)
        batch = services.submit_mapping(request.user, problem_id, self.input(MappingSetInput), self.audit_request_id)
        return self.success(batch_data(batch), status=202)


class ReviewList(KnowledgeAPIView):
    def get(self, request):
        services.require_admin(request.user, super_only=True)
        params = self.params(("page", "page_size", "object_type", "submitter_id", "status", "updated_from", "updated_to", "keyword"),
                             pagination=True)
        return self.success(queries.review_queue(params))


class ReviewDetail(KnowledgeAPIView):
    def get(self, request, object_type, object_key):
        services.require_admin(request.user, super_only=True)
        self.params(())
        return self.success(queries.review_detail(services.get_review(object_type, object_key), request.user))


class ReviewApprove(KnowledgeAPIView):
    approve = True

    def post(self, request, object_type, object_key):
        services.require_admin(request.user, super_only=True)
        data = self.input(ReviewInput if self.approve else RejectInput)
        obj = services.review(request.user, object_type, object_key, data, self.approve, self.audit_request_id)
        return self.success(queries.review_item(obj))


class ReviewReject(ReviewApprove):
    approve = False

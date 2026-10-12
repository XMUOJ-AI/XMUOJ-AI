import re
from urllib.parse import unquote_to_bytes

from rest_framework import serializers
from utils.contract_api import ContractAPIView, ContractSerializer, idempotency_key
from . import services


class RefreshInput(ContractSerializer):
    target_knowledge_code = serializers.RegexField(r"^[a-z][a-z0-9_]{0,63}$", allow_null=True, required=False)


class ClassQuery(ContractSerializer):
    class_id = serializers.UUIDField()


class WeaknessQuery(ContractSerializer):
    limit = serializers.IntegerField(min_value=1, max_value=10, default=5)


def validate(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def query_data(request):
    if any(len(values) != 1 for _, values in request.query_params.lists()):
        services.fail("INPUT_INVALID", "查询参数不能重复")
    return request.query_params.dict()


def audit_reason(request):
    """Decode the HTTP wire representation once; services receive Unicode text."""
    value = request.headers.get("X-Audit-Reason", "")
    if (len(value) > 4096 or re.search(r"[^\x20-\x7e]|%(?![0-9A-Fa-f]{2})", value)):
        services.fail("INPUT_INVALID", "审计理由须为 UTF-8 百分号编码，编码后最长 4096 字节")
    try:
        reason = unquote_to_bytes(value).decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        services.fail("INPUT_INVALID", "审计理由不是有效的 UTF-8")
    if len(reason) > 1000 or re.search(r"[\x00-\x1f\x7f-\x9f]", reason):
        services.fail("INPUT_INVALID", "审计理由最长 1000 个字符且不能含控制字符")
    return reason.strip()


class ProfileAPI(ContractAPIView):
    def get(self, request):
        if request.query_params:
            services.fail("INPUT_INVALID", "不支持额外查询参数")
        return self.success(services.student_profile(request.user.pk))


class WeaknessAPI(ContractAPIView):
    def get(self, request):
        data = validate(WeaknessQuery, query_data(request))
        return self.success(services.weakness(request.user.pk, **data))


class PathAPI(ContractAPIView):
    def get(self, request):
        if request.query_params:
            services.fail("INPUT_INVALID", "不支持额外查询参数")
        return self.success(services.current_path(request.user.pk))


class RefreshAPI(ContractAPIView):
    def post(self, request):
        data = validate(RefreshInput, request.data)
        key = idempotency_key(request, "LEARNING_INPUT_INVALID") if "Idempotency-Key" in request.headers else None
        response = self.success(services.refresh_path(request.user.pk, data.get("target_knowledge_code"), key))
        return response

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        if response.status_code == 429:
            from django.conf import settings
            response["Retry-After"] = str(getattr(settings, "LEARNING_REFRESH_INTERVAL", 10))
        return response


class TeacherProfileAPI(ContractAPIView):
    def get(self, request, student_id):
        data = validate(ClassQuery, query_data(request))
        services.authorize_class(request.user, data["class_id"], student_id,
                                 audit_reason(request), self.request_id)
        return self.success(services.student_profile(student_id))


class ClassStatsAPI(ContractAPIView):
    def get(self, request):
        data = validate(ClassQuery, query_data(request))
        return self.success(services.class_stats(request.user, data["class_id"],
                            audit_reason(request), self.request_id))

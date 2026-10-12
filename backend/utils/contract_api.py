"""Session-only protocol for new APIs; legacy APIView is intentionally unchanged."""
import hashlib
import json
import logging
import uuid

from django.contrib.auth import get_user
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import OperationalError, connection
from django.http import Http404
from django.urls import Resolver404, resolve
from django.utils.deprecation import MiddlewareMixin
from rest_framework import exceptions, serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from account.middleware import APITokenAuthMiddleware, AdminRoleRequiredMiddleware

logger = logging.getLogger(__name__)


class ContractError(Exception):
    def __init__(self, code, message, status=400, details=None, retryable=False):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status
        self.details = {} if details is None else details
        self.retryable = retryable


class StrictSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        # Reading the session again prevents APPKEY from becoming an alternate
        # identity, including when this view is used outside the main middleware.
        user = get_user(request._request)
        if not user.is_authenticated or user.is_disabled:
            return None
        self.enforce_csrf(request)
        return user, None

    def authenticate_header(self, request):
        return "Session"


class ContractAPIView(APIView):
    authentication_classes = (StrictSessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser, FormParser, MultiPartParser)
    contract_version = "1.0.0"
    error_prefix = "LEARNING"

    def initialize_request(self, request, *args, **kwargs):
        self.request_id = "req_" + uuid.uuid4().hex
        return super().initialize_request(request, *args, **kwargs)

    def success(self, data=None, status=200):
        if status == 204:
            return Response(status=204)
        return Response({"error": None, "data": data, "request_id": self.request_id}, status=status)

    def fail(self, code, message, status=400, details=None, retryable=False):
        return Response({
            "error": code,
            "data": {"message": message, "retryable": retryable, "details": {} if details is None else details},
            "request_id": self.request_id,
        }, status=status)

    def handle_exception(self, exc):
        if isinstance(exc, ContractError):
            return self.fail(exc.code, exc.message, exc.status, exc.details, exc.retryable)
        if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
            return self.fail(self.error_prefix + "_AUTH_REQUIRED", "请先登录", 401)
        if isinstance(exc, (exceptions.PermissionDenied, DjangoPermissionDenied)):
            message = "CSRF 校验失败" if "CSRF" in str(exc) else "没有此操作权限"
            return self.fail(self.error_prefix + "_PERMISSION_DENIED", message, 403)
        if isinstance(exc, (exceptions.ValidationError, exceptions.ParseError, exceptions.UnsupportedMediaType)):
            details = exc.detail if isinstance(exc.detail, dict) else {}
            return self.fail(self.error_prefix + "_INPUT_INVALID", "请求格式或字段不合法", 400, details)
        if isinstance(exc, (Http404, exceptions.NotFound)):
            return self.fail(self.error_prefix + "_NOT_FOUND", "资源不存在或无权访问", 404)
        if isinstance(exc, exceptions.MethodNotAllowed):
            return self.fail(self.error_prefix + "_METHOD_NOT_ALLOWED", "不支持此请求方法", 405)
        if isinstance(exc, exceptions.Throttled):
            return self.fail(self.error_prefix + "_RATE_LIMITED", "请求过于频繁", 429, retryable=True)
        if isinstance(exc, OperationalError):
            return self.fail(self.error_prefix + "_DEPENDENCY_NOT_READY", "数据库暂时不可用，请稍后重试", 503, retryable=True)
        # Exception text can contain SQL values, source code, tokens or provider
        # bodies. Correlate errors without copying those values into shared logs.
        logger.error("contract_error request_id=%s type=%s", self.request_id, type(exc).__name__)
        return self.fail(self.error_prefix + "_INTERNAL_ERROR", "服务暂时不可用", 500, retryable=True)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["X-API-Version"] = self.contract_version
        response["X-Request-ID"] = self.request_id
        response["Cache-Control"] = "private, no-store"
        return response


class ContractSerializer(serializers.Serializer):
    """DRF otherwise silently ignores fields outside the declared contract."""
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({"body": "必须是 JSON 对象"})
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({"fields": "包含未定义的字段"})
        return super().to_internal_value(data)


class ContractBoundaryMiddleware(MiddlewareMixin):
    def process_request(self, request):
        try:
            view = resolve(request.path_info).func
        except Resolver404:
            return
        view_class = getattr(view, "view_class", None) or getattr(view, "cls", None)
        request.is_contract_api = isinstance(view_class, type) and issubclass(view_class, ContractAPIView)


class ContractTokenAuthMiddleware(APITokenAuthMiddleware):
    def process_request(self, request):
        if not getattr(request, "is_contract_api", False):
            return super().process_request(request)


class ContractAdminRoleMiddleware(AdminRoleRequiredMiddleware):
    def process_request(self, request):
        # New APIs authorize themselves, including teaching-class members who
        # deliberately are not global administrators. Legacy requests are intact.
        if not getattr(request, "is_contract_api", False):
            return super().process_request(request)


def request_fingerprint(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def idempotency_key(request, error_code):
    key = request.META.get("HTTP_IDEMPOTENCY_KEY", "")
    if not key or len(key) > 100 or key.strip() != key or any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
        raise ContractError(error_code, "Idempotency-Key 必须为 1 至 100 个可见 ASCII 字符")
    return key


def transaction_lock(namespace, identity):
    """Serialize a domain key until commit; always call within atomic()."""
    if not connection.in_atomic_block:
        raise RuntimeError("transaction_lock requires transaction.atomic")
    if connection.vendor == "postgresql":
        key = int.from_bytes(hashlib.sha256((namespace + ":" + str(identity)).encode()).digest()[:8], "big", signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])

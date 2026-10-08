import json
import logging
import re
import uuid
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.views import View


logger = logging.getLogger(__name__)
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CATEGORIES = {"basic", "data_structure", "algorithm", "paradigm", "mathematics", "string", "graph"}


class KnowledgeError(Exception):
    def __init__(self, code, status=400, message=None, details=None):
        self.code = code
        self.status = status
        self.message = message or code
        self.details = details or {}
        super().__init__(self.message)


class KnowledgeAPIView(View):
    """Independent knowledge API envelope; existing APIView remains untouched."""

    def dispatch(self, request, *args, **kwargs):
        supplied = request.META.get("HTTP_X_REQUEST_ID", "")
        self.request_id = supplied if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", supplied) else str(uuid.uuid4())
        try:
            if not request.user.is_authenticated or getattr(request, "auth_method", None) == "api_key":
                raise KnowledgeError("KNOWLEDGE_AUTH_REQUIRED", 401)
            if request.user.is_disabled:
                raise KnowledgeError("KNOWLEDGE_PERMISSION_DENIED", 403)
            if request.method.lower() not in self.http_method_names or not hasattr(self, request.method.lower()):
                raise KnowledgeError("KNOWLEDGE_METHOD_NOT_ALLOWED", 405)
            return super().dispatch(request, *args, **kwargs)
        except KnowledgeError as exc:
            return self.reply({"message": exc.message, "retryable": exc.status >= 500, "details": exc.details}, exc.status, exc.code)
        except Exception:
            logger.exception("Knowledge API request failed: %s", self.request_id)
            return self.reply({"message": "Internal knowledge API error", "retryable": True, "details": {}}, 500, "KNOWLEDGE_INTERNAL_ERROR")

    def reply(self, data, status=200, error=None):
        response = JsonResponse({"error": error, "data": data, "request_id": self.request_id}, status=status)
        response["X-API-Version"] = "0.9.9"
        return response

    @staticmethod
    def body(request, allowed, required=()):
        if not request.content_type.startswith("application/json"):
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "JSON body required")
        try:
            value = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "Invalid JSON body")
        if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "Invalid request fields")
        return value

    @staticmethod
    def query(request, allowed):
        if set(request.GET) - set(allowed) or any(len(values) != 1 for _, values in request.GET.lists()):
            raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "Invalid query parameters")
        return request.GET


def require_admin(user):
    if not user.is_admin_role() or (not user.is_super_admin() and user.problem_permission == "None"):
        raise KnowledgeError("KNOWLEDGE_PERMISSION_DENIED", 403)


def require_super(user):
    if not user.is_super_admin():
        raise KnowledgeError("KNOWLEDGE_PERMISSION_DENIED", 403)


def integer(value, minimum, maximum, default=None):
    if value is None:
        return default
    if isinstance(value, bool) or not re.fullmatch(r"(?:0|[1-9][0-9]*)", str(value)):
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "Invalid integer")
    result = int(value)
    if result < minimum or result > maximum:
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "Integer outside allowed range")
    return result


def code(value):
    if not isinstance(value, str) or not CODE_RE.fullmatch(value):
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "Invalid knowledge code")
    return value


def category(value):
    if value is not None and value not in CATEGORIES:
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "Invalid category")
    return value


def text(value, minimum=0, maximum=500):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "Invalid text length")
    return value.strip()


def weight(value, business_code="KNOWLEDGE_INPUT_INVALID"):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "Invalid weight")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise KnowledgeError("KNOWLEDGE_INPUT_INVALID", 400, "Invalid weight")
    if not number.is_finite() or number <= 0 or number > 1 or number.as_tuple().exponent < -3:
        raise KnowledgeError(business_code, 422, "Weight must be 0.001 to 1")
    return number


def page_params(query):
    return integer(query.get("page"), 1, 1000000, 1), integer(query.get("page_size"), 1, 100, 20)

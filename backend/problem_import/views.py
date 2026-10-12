from django.core import signing
from rest_framework import serializers
from rest_framework.permissions import BasePermission

from utils.contract_api import ContractAPIView, ContractError, ContractSerializer, idempotency_key

from .models import PROBLEM_STATUSES
from .services import batch_data, can_import, get_batch, receive_archive, request_commit
from .tasks import commit_import_batch, validate_import_batch
from .upload import BoundedUploadHandler


class AdminOnly(BasePermission):
    # Import creates problems, so it follows the legacy problem_permission_required rule.
    def has_permission(self, request, view):
        return can_import(request.user)


class ImportAPIView(ContractAPIView):
    error_prefix = "IMPORT"
    permission_classes = ContractAPIView.permission_classes + (AdminOnly,)


def enqueue(actor, ident):
    try:
        actor.send(str(ident))
    except Exception:
        raise ContractError("IMPORT_QUEUE_UNAVAILABLE", "任务队列暂不可用；重试相同请求即可恢复", 503, retryable=True)


class UploadBatchAPI(ImportAPIView):
    def initialize_request(self, request, *args, **kwargs):
        request.upload_handlers.insert(0, BoundedUploadHandler(request))
        return super().initialize_request(request, *args, **kwargs)

    def handle_exception(self, exc):
        if getattr(self.request._request, "problem_import_too_large", False):
            return self.fail("IMPORT_SIZE_LIMIT", "ZIP 超过 Web 大小限制", 413)
        return super().handle_exception(exc)

    def post(self, request):
        data = request.data
        if getattr(request._request, "problem_import_too_large", False):
            raise ContractError("IMPORT_SIZE_LIMIT", "ZIP 超过 Web 大小限制", 413)
        if set(data) != {"archive"} or len(request.FILES.getlist("archive")) != 1:
            raise ContractError("IMPORT_INPUT_INVALID", "请求必须且只能包含一个 archive 文件")
        archive = request.FILES.get("archive")
        if archive is None:
            raise ContractError("IMPORT_INPUT_INVALID", "缺少 ZIP 文件")
        batch, created = receive_archive(archive, request.user)
        if batch.status == "uploaded":
            enqueue(validate_import_batch, batch.pk)
        response = self.success(batch_data(batch), 202)
        response["Location"] = "/api/admin/problem-import/batches/" + batch.batch_key
        return response


class BatchAPI(ImportAPIView):
    def get(self, request, batch_id):
        return self.success(batch_data(get_batch(batch_id, request.user)))


def page(request, batch, kind, rows):
    allowed = {"cursor", "limit", "status"} if kind == "problems" else {"cursor", "limit"}
    if set(request.query_params) - allowed:
        raise ContractError("IMPORT_INPUT_INVALID", "包含未定义查询参数")
    try:
        limit = int(request.query_params.get("limit", "100"))
        if not 1 <= limit <= 500:
            raise ValueError()
    except ValueError:
        raise ContractError("IMPORT_INPUT_INVALID", "limit 必须为 1 至 500")
    status = request.query_params.get("status", "")
    if status and status not in PROBLEM_STATUSES:
        raise ContractError("IMPORT_INPUT_INVALID", "未知题目状态")
    scope = [batch.batch_key, kind, status]
    cursor = request.query_params.get("cursor")
    position = (0, 0)
    if cursor is not None:
        try:
            if not 1 <= len(cursor) <= 500:
                raise ValueError()
            payload = signing.loads(cursor, salt="problem-import-cursor")
            if payload["scope"] != scope or len(payload["after"]) != 2:
                raise ValueError()
            position = tuple(payload["after"])
            if any(type(value) is not int or value < 0 for value in position):
                raise ValueError()
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            raise ContractError("IMPORT_CURSOR_INVALID", "游标无效或不属于当前查询")
    selected = sorted((row for row in rows if (row["line_number"] or 0, row["id"]) > position
                       and (not status or row["status"] == status)),
                      key=lambda row: (row["line_number"] or 0, row["id"]))[:limit + 1]
    more = len(selected) > limit
    selected = selected[:limit]
    next_cursor = None
    if more:
        last = selected[-1]
        next_cursor = signing.dumps({"scope": scope, "after": [last["line_number"] or 0, last["id"]]},
                                    salt="problem-import-cursor", compress=True)
    return {"items": selected, "page": {"next_cursor": next_cursor, "has_more": more, "limit": limit}}


class BatchProblemsAPI(ImportAPIView):
    def get(self, request, batch_id):
        batch = get_batch(batch_id, request.user)
        rows = [{"id": row.pk, "line_number": row.line_number,
                 "problem_key": row.standardized_data["problem_key"], "source_platform": row.source_platform,
                 "source_id": row.source_id, "title": row.title, "status": row.import_status,
                 "issue_count": len(row.validation_errors), "imported_problem_id": row.imported_problem_id}
                for row in batch.problems.defer("raw_data").iterator()]
        return self.success(page(request, batch, "problems", rows))


class BatchErrorsAPI(ImportAPIView):
    def get(self, request, batch_id):
        batch = get_batch(batch_id, request.user)
        rows = [dict(value, id=index, line_number=None) for index, value in enumerate(batch.issues, 1)]
        for row in batch.problems.only("line_number", "validation_errors").iterator():
            rows.extend(dict(value, id=row.pk * 1000 + index, line_number=row.line_number)
                        for index, value in enumerate(row.validation_errors, 1))
        return self.success(page(request, batch, "errors", rows))


class CommitInput(ContractSerializer):
    allow_partial = serializers.BooleanField()
    problem_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), max_length=5000)
    acknowledged_warning_codes = serializers.ListField(
        child=serializers.RegexField(r"^[A-Z][A-Z0-9_]+$"), max_length=100)

    def validate(self, data):
        raw = self.initial_data
        if type(raw.get("allow_partial")) is not bool:
            raise serializers.ValidationError({"allow_partial": "必须为 JSON boolean"})
        if not isinstance(raw.get("problem_ids"), list) or any(type(value) is not int for value in raw["problem_ids"]):
            raise serializers.ValidationError({"problem_ids": "必须为 JSON integer 数组"})
        if (not isinstance(raw.get("acknowledged_warning_codes"), list)
                or any(not isinstance(value, str) for value in raw["acknowledged_warning_codes"])):
            raise serializers.ValidationError({"acknowledged_warning_codes": "必须为字符串数组"})
        for key in ("problem_ids", "acknowledged_warning_codes"):
            if len(data[key]) != len(set(data[key])):
                raise serializers.ValidationError({key: "元素不可重复"})
        return data


class CommitBatchAPI(ImportAPIView):
    def post(self, request, batch_id):
        get_batch(batch_id, request.user)
        key = idempotency_key(request, "IMPORT_IDEMPOTENCY_KEY_REQUIRED")
        serializer = CommitInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch, response, send = request_commit(batch_id, request.user, key, serializer.validated_data)
        if send:
            enqueue(commit_import_batch, batch.pk)
        return self.success(response, 202)

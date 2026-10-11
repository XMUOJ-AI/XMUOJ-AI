import hashlib
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Count, F, Q
from django.db.models.functions import MD5
from account.models import User
from django.utils import timezone
from knowledge.models import KnowledgePoint, KnowledgeDependency, ProblemKnowledge
from learning.models import StudentKnowledgeState
from learning.services import current_path
from submission.models import Submission
from rag.adapters import config
from rag.models import RagDocument
from utils.contract_api import ContractError, request_fingerprint, transaction_lock
from .contracts import validate_api
from .models import AgentConversation, AgentRun, AgentDispatch, AIFeedbackReview, ErrorPattern
from .tools import visible_problem, owned_submission, timestamp, append_message, problem_version


def fail(code, message, status=400, retryable=False):
    raise ContractError("AGENT_" + code, message, status, retryable=retryable)


def learning_path(user_id):
    try:
        return current_path(user_id)
    except ContractError:
        fail("DEPENDENCY_NOT_READY", "尚无可用的活动学习路径", 503, True)


def model_ready():
    if not config("AGENT_MODEL_URL") or not config("AGENT_MODEL_NAME"):
        fail("DEPENDENCY_NOT_READY", "模型服务尚未配置", 503, True)


def conversation_data(conversation):
    return {"conversation_id": str(conversation.pk), "problem_id": conversation.problem._id,
            "service_type": conversation.service_type, "status": conversation.status,
            "hint_level": conversation.current_hint_level, "max_hint_level": 3,
            "hint_available_time": timestamp(conversation.hint_available_time), "first_opened_time": timestamp(conversation.first_opened_time)}


@transaction.atomic
def start_conversation(user, data):
    if not isinstance(data, dict) or set(data) != {"problem_id", "service_type"} or data.get(
            "service_type") != "socratic_hint" or not isinstance(data.get("problem_id"), str) or not 1 <= len(data["problem_id"]) <= 100:
        fail("INPUT_INVALID", "会话须指定problem_id与socratic_hint类型")
    problem = visible_problem(data["problem_id"])
    transaction_lock("agent-user", user.pk)
    conversation, created = AgentConversation.objects.get_or_create(user=user, problem=problem, service_type="socratic_hint", status="active",
                                                                    defaults={"hint_available_time": timezone.now() + timedelta(seconds=int(config("AGENT_THINK_SECONDS", 180)))})
    return conversation, created


def authorize_run(user, run_id, check_sources=True):
    try:
        key = UUID(str(run_id))
    except ValueError:
        fail("INPUT_INVALID", "run_id必须是UUID")
    if not User.objects.filter(pk=user.pk, is_disabled=False).exists():
        fail("PERMISSION_DENIED", "账户不可用", 403)
    run = AgentRun.objects.select_related("problem", "submission", "conversation").filter(pk=key, user=user).first()
    if not run:
        fail("RUN_NOT_FOUND", "运行不存在或无权访问", 404)
    if run.problem_id:
        visible_problem(run.problem._id)
    if run.submission_id:
        sub = owned_submission(user.pk, run.submission_id)
        if run.input_payload.get("_submission_snapshot") != {"code_sha256": hashlib.sha256(sub.code.encode()).hexdigest(), "language": sub.language, "verdict": sub.result}:
            fail("DEPENDENCY_NOT_READY", "提交内容或判题结果已更新，请重新分析", 503, True)
    if run.service_type == "learning_path_explanation":
        try:
            path = learning_path(user.pk)
        except ContractError:
            fail("DEPENDENCY_NOT_READY", "活动路径已失效，请重新生成解释", 503, True)
        if path["path_id"] != run.input_payload.get("path_id") or any(not x["problem_id"]
                                                                      for x in path["steps"] if x["order"] in run.input_payload.get("_path_problem_orders", [])):
            fail("DEPENDENCY_NOT_READY", "路径或题目可见性已变化，请重新生成解释", 503, True)
    if check_sources and run.input_payload.get("_source_version") != context_versions(
            user.pk, run.input_payload.get("_problem_ids", []), run.input_payload.get("_knowledge_ids", [])):
        fail("DEPENDENCY_NOT_READY", "教学资料已变化，请创建新运行", 503, True)
    if check_sources:
        from .tools import check_references
        source_run = run.cached_from if run.cached_from_id else run
        for refs in source_run.tool_calls.filter(status="succeeded").values_list("result_summary", flat=True):
            check_references(refs.get("references", {}))
    return run


def context_versions(user_id, problem_ids, knowledge_ids):
    # Scope fingerprints to this request. Empty/deleted rows alter the fingerprint too.
    profile = StudentKnowledgeState.objects.filter(user_id=user_id, knowledge_point_id__in=knowledge_ids)
    document_scope = Q(metadata__knowledge_id__in=knowledge_ids) | Q(metadata__problem_id__in=problem_ids)
    return request_fingerprint({
        "knowledge": list(KnowledgePoint.objects.filter(pk__in=knowledge_ids).order_by("id").values_list("id", "version", "status")),
        "edges": list(KnowledgeDependency.objects.filter(Q(prerequisite_id__in=knowledge_ids) | Q(dependent_id__in=knowledge_ids)).order_by("id").values_list("id", "version")),
        "mappings": list(ProblemKnowledge.objects.filter(problem___id__in=problem_ids).order_by("id").values_list("id", "knowledge_point_id", "review_status", "role", "weight")),
        "profile": list(profile.order_by("id").values_list("id", "updated_time")),
        "rag": list(RagDocument.objects.filter(document_scope).order_by("id").values_list("id", "content_hash", "status", "access_scope", "updated_time")),
        "patterns": list(ErrorPattern.objects.filter(Q(problem___id__in=problem_ids) | Q(knowledge_point_id__in=knowledge_ids))
                         .order_by("id").values_list("id", "review_status", "updated_time")),
        "problems": [(x.pk, problem_version(x), x.visible) for x in visible_problem_queryset(problem_ids).order_by("id")],
        "submission_counts": Submission.objects.filter(user_id=user_id, problem___id__in=problem_ids).aggregate(total=Count("pk"), accepted=Count("pk", filter=Q(result=0))),
        "recent": list(Submission.objects.filter(user_id=user_id, problem___id__in=problem_ids).annotate(code_digest=MD5("code"))
                       .order_by("-create_time", "-id").values_list("id", "result", "code_digest")[:6]),
    })


def visible_problem_queryset(problem_ids):
    from problem.models import Problem
    return Problem.objects.filter(_id__in=problem_ids, contest__isnull=True)


@transaction.atomic
def create_run(user, data, key):
    validate_api("CreateRunRequest", data)
    transaction_lock("agent-user", user.pk)
    submission, problem, conversation = None, None, None
    payload = dict(data)
    context = {"user_id": user.pk, "request": data, "prompt": "agent-v1", "model": config("AGENT_MODEL_NAME", ""),
               "model_config_version": config("AGENT_MODEL_CONFIG_VERSION", "v1")}
    service = data["service_type"]
    if "submission_id" in data:
        submission = owned_submission(user.pk, data["submission_id"])
        problem = submission.problem
        if submission.result in (6, 7):
            fail("SUBMISSION_NOT_FINAL", "判题尚未完成", 409, True)
        if len(submission.code.encode()) > 100 * 1024:
            fail("INPUT_TOO_LARGE", "代码超过100KiB限制", 413)
        context.update(code_hash=hashlib.sha256(submission.code.encode()).hexdigest(), verdict=submission.result)
        payload["_submission_snapshot"] = {"code_sha256": context["code_hash"], "language": submission.language, "verdict": submission.result}
    if service == "socratic_hint":
        problem = visible_problem(data["problem_id"])
        conversation = AgentConversation.objects.select_for_update().filter(pk=data["conversation_id"], user=user, problem=problem, status="active").first()
        if not conversation:
            fail("CONVERSATION_NOT_FOUND", "会话不存在或不匹配", 404)
    if service == "learning_path_explanation":
        path = learning_path(user.pk)
        if data.get("path_id") and data["path_id"] != path["path_id"]:
            fail("DEPENDENCY_NOT_READY", "活动路径不存在或已变化", 503, True)
        if not path["steps"]:
            fail("DEPENDENCY_NOT_READY", "活动路径暂无可解释步骤", 503, True)
        payload["path_id"] = path["path_id"]
        context["path"] = path
        payload["_path_problem_orders"] = [x["order"] for x in path["steps"] if x["problem_id"]]
    fingerprint = request_fingerprint(data)
    previous = AgentRun.objects.filter(user=user, idempotency_key=key).first()
    if previous:
        if previous.request_hash != fingerprint:
            fail("IDEMPOTENCY_CONFLICT", "幂等键已用于不同请求", 409)
        authorize_run(user, previous.pk)
        return previous, False
    if conversation:
        if not data["student_explanation"].strip():
            fail("INPUT_INVALID", "请先提交自己的解题思路")
        if conversation.current_hint_level >= 3:
            fail("HINT_LEVEL_CONFLICT", "当前会话已达到三级提示上限", 409)
        if conversation.hint_available_time > timezone.now():
            fail("HINT_NOT_AVAILABLE", "请先独立思考，等待提示时间到达", 409, True)
        if AgentRun.objects.filter(conversation=conversation, status__in=("queued", "running")).exists():
            fail("RATE_LIMITED", "当前会话已有运行", 429, True)
        context["hint_level"] = conversation.current_hint_level + 1
        payload["expected_hint_level"] = conversation.current_hint_level + 1
    problem_ids = [problem._id] if problem else [x["problem_id"] for x in path["steps"] if x["problem_id"]]
    knowledge_ids = set(ProblemKnowledge.objects.filter(problem___id__in=problem_ids, review_status="approved").values_list("knowledge_point_id", flat=True))
    if service in ("socratic_hint", "learning_path_explanation"):
        knowledge_ids.update(StudentKnowledgeState.objects.filter(user_id=user.pk).values_list("knowledge_point_id", flat=True))
    if service == "learning_path_explanation":
        knowledge_ids.update(KnowledgePoint.objects.filter(code__in=[x["knowledge_code"] for x in path["steps"]]).values_list("pk", flat=True))
    payload["_problem_ids"], payload["_knowledge_ids"] = sorted(problem_ids), sorted(knowledge_ids)
    context["versions"] = context_versions(user.pk, payload["_problem_ids"], payload["_knowledge_ids"])
    payload["_source_version"] = context["versions"]
    input_hash = request_fingerprint(context)
    cached = AgentRun.objects.filter(user=user, input_hash=input_hash, status="succeeded", safety_status="passed", cached_from__isnull=True,
                                     created_time__gt=timezone.now() - timedelta(minutes=30)).order_by("-created_time").first() if not conversation else None
    if cached:
        authorize_run(user, cached.pk)
    if not cached:
        model_ready()
        if AgentRun.objects.filter(user=user, status__in=("queued", "running")).count() >= 2:
            fail("RATE_LIMITED", "同时运行数达到限制", 429, True)
    if AgentRun.objects.filter(user=user, created_time__gt=timezone.now() - timedelta(minutes=1)).count() >= 6:
        fail("RATE_LIMITED", "每分钟最多创建6个运行", 429, True)
    run = AgentRun.objects.create(user=user, service_type=service, problem=problem, submission=submission, conversation=conversation,
                                  idempotency_key=key, request_hash=fingerprint, input_hash=input_hash, input_payload=payload,
                                  provider="http", model_name=config("AGENT_MODEL_NAME", ""), cached_from=(cached.cached_from or cached) if cached else None,
                                  status="succeeded" if cached else "queued", output_payload=cached.output_payload if cached else None,
                                  safety_status="passed" if cached else "pending", finished_time=timezone.now() if cached else None)
    if conversation:
        append_message(conversation, "user", data["student_explanation"], run.pk)
    if not cached:
        AgentDispatch.objects.create(run=run)
        transaction.on_commit(lambda: deliver_run(run.pk))
    return run, not bool(cached)


def deliver_run(run_id):
    from .tasks import execute_agent_run
    with transaction.atomic():
        dispatch = AgentDispatch.objects.select_for_update().filter(run_id=run_id, delivered_time__isnull=True).first()
        if not dispatch or dispatch.run.status != "queued":
            return False
        dispatch.attempts = F("attempts") + 1
        dispatch.save(update_fields=["attempts"])
        try:
            execute_agent_run.send(str(run_id))
        except Exception:
            # Durable intent remains pending. No broker address/credentials enter logs or responses.
            return False
        dispatch.delivered_time = timezone.now()
        dispatch.save(update_fields=["delivered_time"])
        return True


def run_data(run):
    return {"run_id": str(run.pk), "service_type": run.service_type, "status": run.status, "cached": run.cached_from_id is not None,
            "result": run.output_payload if run.status == "succeeded" else None,
            "error_detail": {"code": run.error_code, "message": run.error_message, "retryable": run.error_retryable, "details": {}} if run.error_code else None,
            "created_time": timestamp(run.created_time), "started_time": timestamp(run.started_time), "finished_time": timestamp(run.finished_time)}


@transaction.atomic
def feedback(user, run_id, data):
    validate_api("FeedbackRequest", data)
    run = authorize_run(user, run_id)
    if run.status != "succeeded":
        fail("RUN_NOT_FINISHED", "仅完成的运行可以评价", 409, True)
    review, _ = AIFeedbackReview.objects.update_or_create(run=run, user=user, defaults={"rating": data["rating"], "comment": data.get("comment", "")})
    return {"run_id": str(run.pk), "rating": review.rating, "updated_time": timestamp(review.updated_time)}

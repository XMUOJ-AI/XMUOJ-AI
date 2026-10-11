"""Internal tools have no HTTP route. Context derives solely from an owned AgentRun."""
import hashlib
import json
import re
import time
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.html import strip_tags
from jsonschema import Draft7Validator

from knowledge.models import KnowledgePoint, KnowledgeDependency, ProblemKnowledge
from learning import services as learning
from problem.models import Problem
from rag import services as rag
from rag.models import RagDocument, RagChunk
from submission.models import Submission
from utils.contract_api import ContractError, request_fingerprint
from .contracts import ALLOWLIST, tool_schema
from .models import AgentConversation, AgentMessage, AgentToolCall, ErrorPattern
from .safety import check_output

VERDICTS = {-2: "CE", -1: "WA", 0: "AC", 1: "TLE", 2: "TLE", 3: "MLE", 4: "RE", 5: "SE", 6: "Pending", 7: "Judging", 8: "PartialAC"}


def timestamp(dt):
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def visible_problem(display_id):
    problem = Problem.objects.filter(_id=display_id, visible=True, contest__isnull=True).first()
    if problem is None:
        raise ContractError("AGENT_PROBLEM_NOT_FOUND", "题目不存在或无权访问", 404)
    return problem


def owned_submission(user_id, submission_id):
    sub = Submission.objects.select_related("problem").filter(pk=submission_id, user_id=user_id).first()
    if sub is None or not sub.problem.visible or sub.problem.contest_id is not None:
        raise ContractError("AGENT_SUBMISSION_NOT_FOUND", "提交不存在或无权访问", 404)
    return sub


def knowledge_point(pk):
    point = KnowledgePoint.objects.filter(pk=pk, status="active").first()
    if point is None:
        raise ContractError("AGENT_NOT_FOUND", "知识点不存在或不可用", 404)
    return point


def knowledge_ref(point):
    return {"knowledge_id": point.pk, "knowledge_code": point.code, "name": point.name}


def problem_knowledge(problem):
    rows = ProblemKnowledge.objects.filter(problem=problem, knowledge_point__status="active",
                                           review_status="approved").select_related("knowledge_point").order_by("knowledge_point__code")
    return {"problem_id": problem._id, "knowledge_points": [dict(knowledge_ref(x.knowledge_point), role=x.role,
            weight=float(x.weight), description=x.knowledge_point.description) for x in rows[:100]]}


def submission_data(sub, include_code=True):
    stats = sub.statistic_info or {}
    result = {"submission_id": str(sub.pk), "problem_id": sub.problem._id, "language": sub.language,
              "verdict": VERDICTS.get(sub.result, "Unknown"), "created_time": timestamp(sub.create_time)}
    if include_code:
        if len(sub.code.encode()) > 100 * 1024:
            raise ContractError("AGENT_INPUT_TOO_LARGE", "代码超过100KiB限制", 413)
        result.update(code=sub.code, code_sha256=hashlib.sha256(sub.code.encode()).hexdigest(), is_final=sub.result not in (6, 7),
                      time_cost_ms=stats.get("time_cost"), memory_cost_bytes=stats.get("memory_cost"),
                      compiler_message=str(stats.get("err_info", ""))[:2000] if sub.result == -2 else None)
    return result


def append_message(conversation, role, text, run_id):
    # Caller holds the conversation row lock; no model controls role, sequence or run.
    msg = AgentMessage.objects.create(conversation=conversation, sequence=(conversation.messages.aggregate(n=Max("sequence"))["n"] or 0) + 1,
                                      role=role, content=text, metadata={"run_id": str(run_id)}, token_count=rag.token_count(text))
    conversation.save(update_fields=["last_active_time"])
    return msg


@dataclass(frozen=True)
class ToolContext:
    run: object
    request_id: str
    deadline: float = None

    @property
    def user_id(self):
        return self.run.user_id

    @property
    def service_type(self):
        return self.run.service_type


def enriched(rows):
    ids = dict(KnowledgePoint.objects.filter(code__in=[x["knowledge_code"] for x in rows], status="active").values_list("code", "id"))
    return [dict(row, knowledge_id=ids[row["knowledge_code"]]) for row in rows if row["knowledge_code"] in ids]


def handle(ctx, name, a):
    if name == "get_student_profile":
        data = learning.student_profile(ctx.user_id)
        return {"user_id": ctx.user_id, "algorithm_version": data["algorithm_version"], "updated_time": data["updated_time"],
                "knowledge_states": enriched(data["knowledge_states"])}
    if name == "get_weak_points":
        data = learning.weakness(ctx.user_id, limit=10)
        return {"user_id": ctx.user_id, "algorithm_version": data["algorithm_version"], "weak_points": enriched(data["weak_points"])}
    if name == "get_learning_path":
        data = learning.current_path(ctx.user_id)
        if ctx.run.input_payload.get("path_id") != data["path_id"]:
            raise ContractError("AGENT_DEPENDENCY_NOT_READY", "学习路径已变化，请创建新运行", 409, retryable=True)
        data["steps"] = enriched(data["steps"])
        if data["target"]:
            data["target"] = enriched([data["target"]])[0]
        return dict(data, user_id=ctx.user_id)
    if name == "get_submission":
        return submission_data(owned_submission(ctx.user_id, a["submission_id"]))
    if name == "get_knowledge_dependencies":
        point = knowledge_point(a["knowledge_id"])
        rows = KnowledgeDependency.objects.filter(dependent=point, prerequisite__status="active").select_related("prerequisite").order_by("prerequisite__code")[:30]
        return {"root": knowledge_ref(point), "prerequisites": [dict(knowledge_ref(x.prerequisite), relation_type=x.relation_type, weight=float(x.weight)) for x in rows]}
    if name == "search_rag":
        knowledge_point(a["knowledge_id"])
        if "problem_id" in a:
            visible_problem(a["problem_id"])
        return rag.search(a["query"], a["knowledge_id"], a.get("problem_id"), timeout=max(0, ctx.deadline - time.monotonic()) if ctx.deadline else None)
    problem = visible_problem(a["problem_id"])
    if name == "get_problem_info":
        return {"problem_id": problem._id, "title": problem.title, "description": strip_tags(problem.description),
                "input_description": strip_tags(problem.input_description), "output_description": strip_tags(problem.output_description),
                "samples": problem.samples, "difficulty": {"Low": 1, "Mid": 3, "High": 5}.get(problem.difficulty, 3),
                "time_limit_ms": problem.time_limit, "memory_limit_mb": problem.memory_limit,
                "tags": list(problem.tags.values_list("name", flat=True)[:30])}
    if name == "get_problem_summary":
        return {"problem_id": problem._id, "title": problem.title, "summary": strip_tags(problem.description)[:1600],
                "constraints_summary": strip_tags(problem.input_description)[:400],
                "difficulty": {"Low": 1, "Mid": 3, "High": 5}.get(problem.difficulty, 3)}
    if name == "get_problem_knowledge":
        return problem_knowledge(problem)
    if name == "get_knowledge_context":
        data = problem_knowledge(problem)
        rows = KnowledgeDependency.objects.filter(dependent_id__in=[x["knowledge_id"] for x in data["knowledge_points"]],
                                                  prerequisite__status="active").select_related("prerequisite").order_by("prerequisite__code")[:30]
        data["prerequisites"] = [dict(knowledge_ref(x.prerequisite), relation_type=x.relation_type, weight=float(x.weight)) for x in rows]
        data["context_summary"] = "本题训练：" + "、".join(x["name"] for x in data["knowledge_points"]) + "。直接前置：" + "、".join(x["name"] for x in data["prerequisites"])
        return data
    if name in ("get_student_recent_submissions", "get_student_problem_history"):
        subs = Submission.objects.filter(user_id=ctx.user_id, problem=problem).order_by("-create_time", "-id")
        rows = list(subs[:6])
        result = {"user_id": ctx.user_id, "problem_id": problem._id, "attempt_count": subs.count(),
                  "recent_submissions": [submission_data(x, False) for x in rows[:5]]}
        if name == "get_student_problem_history":
            result["accepted"] = subs.filter(result=0).exists()
            for i, item in enumerate(result["recent_submissions"]):
                item["code_changed"] = i + 1 >= len(rows) or rows[i].code != rows[i + 1].code
        return result
    if name in ("get_error_patterns", "search_error_patterns"):
        ids = ProblemKnowledge.objects.filter(problem=problem, review_status="approved", knowledge_point__status="active").values_list("knowledge_point_id", flat=True)
        patterns = ErrorPattern.objects.filter(Q(problem=problem) | Q(knowledge_point_id__in=ids), review_status="approved", verdict=a["verdict"]).order_by("priority", "code")[:20]
        # Deterministic keyword relevance, never persist or index the student's source code.
        candidates = []
        words = set(re.findall("\\w+", a["code_snippet"].lower()))
        for pattern in patterns:
            terms = set(re.findall("\\w+", pattern.retrieval_text.lower()))
            confidence = len(words & terms) / len(terms) if terms else 0.0
            item = {"code": pattern.code, "cause_short": pattern.cause_short, "fix_direction": pattern.fix_direction,
                    "confidence": min(1.0, confidence), "source": "reviewed"}
            check_output(item)
            candidates.append((confidence, pattern.priority, pattern.code, item))
        return {"patterns": [x[3] for x in sorted(candidates, key=lambda x: (-x[0], x[1], x[2]))[:5]]}
    if name == "get_algorithm_template":
        doc = RagDocument.objects.filter(status="active", access_scope__in=("public", "student"),
                                         metadata__problem_id=problem._id, metadata__has_key="algorithm_template").exclude(source_type="solution").order_by("-updated_time").first()
        if not doc:
            raise ContractError("AGENT_DEPENDENCY_NOT_READY", "此题尚无审核通过的算法模板", 503, retryable=True)
        result = {"problem_id": problem._id, "algorithm_template": doc.metadata["algorithm_template"],
                  "complexity_target": doc.metadata.get("complexity_target", {}), "contains_full_solution": False, "source_ids": [str(doc.pk)]}
        check_output(result)
        return result
    if name in ("get_hint_level", "save_agent_conversation"):
        with transaction.atomic():
            conversation = AgentConversation.objects.select_for_update().filter(pk=ctx.run.conversation_id,
                                                                                user_id=ctx.user_id, problem=problem, status="active").first()
            if not conversation:
                raise ContractError("AGENT_CONVERSATION_NOT_FOUND", "会话不存在或不匹配", 404)
            if name == "get_hint_level":
                return {"user_id": ctx.user_id, "problem_id": problem._id, "hint_level": conversation.current_hint_level,
                        "max_hint_level": 3, "hint_available": conversation.current_hint_level < 3 and conversation.hint_available_time <= timezone.now(),
                        "hint_available_time": timestamp(conversation.hint_available_time), "student_explanation_required": True,
                        "student_explanation_received": bool(ctx.run.input_payload.get("student_explanation"))}
            check_output(a["message"])
            message = append_message(conversation, "assistant", a["message"], ctx.run.pk)
            return {"message_id": message.pk, "saved": True, "created_time": timestamp(message.created_time)}
    raise ContractError("AGENT_TOOL_PERMISSION_DENIED", "工具未注册", 403)


def dispatch(ctx, name, arguments):
    start = time.monotonic()
    # Lock the run to make budgets and sequence numbers resistant to concurrent dispatch.
    with transaction.atomic():
        type(ctx.run).objects.select_for_update().get(pk=ctx.run.pk)
        existing = AgentToolCall.objects.filter(run=ctx.run)
        sequence = existing.count() + 1
        valid_arguments = isinstance(arguments, dict) and name in ALLOWLIST.get(
            ctx.service_type, ()) and Draft7Validator(tool_schema(ctx.service_type, name)).is_valid(arguments)
        if valid_arguments:
            safe_args = {}
            for key, value in arguments.items():
                safe_args[key] = {"sha256": hashlib.sha256(str(value).encode()).hexdigest(), "length": len(str(value))} if key in ("code_snippet", "message", "query") else value
        else:
            safe_args = {"invalid": True, "sha256": request_fingerprint(arguments)}
        log = AgentToolCall.objects.create(run=ctx.run, sequence=sequence, tool_name=str(name)[:64], service_type=ctx.service_type, arguments=safe_args)
        rag_count = existing.filter(tool_name="search_rag").count()
    try:
        if sequence > 8 or (name == "search_rag" and rag_count > 2):
            raise ContractError("AGENT_BUDGET_EXCEEDED", "工具调用次数超过限制", 429)
        if ctx.deadline and time.monotonic() >= ctx.deadline:
            raise ContractError("AGENT_TOOL_TIMEOUT", "工具调用已超时", 504, retryable=True)
        schema = tool_schema(ctx.service_type, name)
        if not Draft7Validator(schema).is_valid(arguments):
            raise ContractError("AGENT_TOOL_ARGUMENT_INVALID", "工具参数不符合签名")
        if "user_id" in arguments and arguments["user_id"] != ctx.user_id:
            raise ContractError("AGENT_TOOL_PERMISSION_DENIED", "无权读取该数据", 403)
        data = handle(ctx, name, arguments)
        if ctx.deadline and time.monotonic() >= ctx.deadline:
            raise ContractError("AGENT_TOOL_TIMEOUT", "工具调用已超时", 504, retryable=True)
        encoded = json.dumps(data, ensure_ascii=False, default=str).encode()
        used = sum(x.get("bytes", 0) for x in AgentToolCall.objects.filter(run=ctx.run, status="succeeded").values_list("result_summary", flat=True))
        if used + len(encoded) > 30 * 1024:
            raise ContractError("AGENT_TOOL_RESULT_TOO_LARGE", "工具累计上下文超过30KiB", 413)
        result = {"ok": True, "data": data, "meta": {"schema_version": "1.0.0", "source_version": request_fingerprint(data), "cached": False, "truncated": False}}
        log.status = "succeeded"
        log.result_summary = {"sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded), "references": result_references(ctx, name, arguments, data)}
    except Exception as exc:
        if not isinstance(exc, ContractError):
            exc = ContractError("AGENT_TOOL_INTERNAL_ERROR", "工具暂时不可用", 500, retryable=True)
        result = {"ok": False, "error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable, "details": exc.details}}
        log.status, log.error_code = "denied" if exc.status == 403 else "failed", exc.code
        log.result_summary = {"error": exc.code}
    log.duration_ms = max(0, int((time.monotonic() - start) * 1000))
    log.save(update_fields=["status", "error_code", "result_summary", "duration_ms"])
    return result


def problem_version(problem):
    return request_fingerprint({"title": problem.title, "description": problem.description, "input": problem.input_description,
                                "output": problem.output_description, "samples": problem.samples, "time": problem.time_limit, "memory": problem.memory_limit,
                                "difficulty": problem.difficulty, "tags": list(problem.tags.order_by("id").values_list("id", "name"))})


def document_version(document):
    return request_fingerprint({"hash": document.content_hash, "metadata": document.metadata, "scope": document.access_scope, "updated": timestamp(document.updated_time)})


def result_references(ctx, name, args, data):
    problem_ids, knowledge_ids = set(), set()

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if isinstance(value.get("problem_id"), str):
                problem_ids.add(value["problem_id"])
            if type(value.get("knowledge_id")) is int:
                knowledge_ids.add(value["knowledge_id"])
            for item in value.values():
                visit(item)
    visit(data)
    if args.get("problem_id"):
        problem_ids.add(args["problem_id"])
    if args.get("knowledge_id"):
        knowledge_ids.add(args["knowledge_id"])
    refs = {"problems": [{"id": key, "version": problem_version(visible_problem(key))} for key in sorted(problem_ids)],
            "knowledge": [{"id": key, "version": knowledge_point(key).version} for key in sorted(knowledge_ids)]}
    if name == "get_submission":
        sub = owned_submission(ctx.user_id, args["submission_id"])
        refs["submissions"] = [{"id": str(sub.pk), "user_id": ctx.user_id, "code_hash": hashlib.sha256(sub.code.encode()).hexdigest(), "verdict": sub.result}]
    if name == "search_rag":
        chunks = RagChunk.objects.select_related("document").filter(pk__in=[x["chunk_id"] for x in data["hits"]])
        refs["chunks"] = [{"id": str(x.pk), "hash": x.content_hash} for x in chunks]
        refs["documents"] = [{"id": str(x.document.pk), "version": document_version(x.document)} for x in chunks]
    if name == "get_algorithm_template":
        refs["documents"] = [{"id": str(x.pk), "version": document_version(x)} for x in RagDocument.objects.filter(pk__in=data["source_ids"])]
    if name in ("get_error_patterns", "search_error_patterns"):
        refs["patterns"] = [{"id": x.pk, "version": timestamp(x.updated_time)} for x in ErrorPattern.objects.filter(code__in=[x["code"] for x in data["patterns"]])]
    if name in ("get_knowledge_dependencies", "get_knowledge_context"):
        ids = [args["knowledge_id"]] if name == "get_knowledge_dependencies" else [x["knowledge_id"] for x in data["knowledge_points"]]
        refs["dependency_scope"] = ids
        refs["dependency_version"] = dependency_version(ids)
    return refs


def dependency_version(ids):
    return request_fingerprint(list(KnowledgeDependency.objects.filter(dependent_id__in=ids).order_by("id").values_list("id", "version")))


def check_references(refs):
    def changed():
        raise ContractError("AGENT_DEPENDENCY_NOT_READY", "引用资料已变化或撤回，请创建新运行", 503, retryable=True)
    for ref in refs.get("problems", []):
        if problem_version(visible_problem(ref["id"])) != ref["version"]:
            changed()
    for ref in refs.get("submissions", []):
        sub = owned_submission(ref["user_id"], ref["id"])
        if sub.result != ref["verdict"] or hashlib.sha256(sub.code.encode()).hexdigest() != ref["code_hash"]:
            changed()
    for ref in refs.get("knowledge", []):
        if knowledge_point(ref["id"]).version != ref["version"]:
            changed()
    for ref in refs.get("documents", []):
        document = RagDocument.objects.filter(pk=ref["id"], status="active", access_scope__in=("public", "student")).exclude(source_type="solution").first()
        if not document or document_version(document) != ref["version"]:
            changed()
        if document.metadata.get("problem_id"):
            visible_problem(document.metadata["problem_id"])
        if document.metadata.get("knowledge_id"):
            knowledge_point(document.metadata["knowledge_id"])
    for ref in refs.get("patterns", []):
        pattern = ErrorPattern.objects.filter(pk=ref["id"], review_status="approved").first()
        if not pattern or timestamp(pattern.updated_time) != ref["version"]:
            changed()
    if "dependency_scope" in refs and dependency_version(refs["dependency_scope"]) != refs["dependency_version"]:
        changed()
    for ref in refs.get("chunks", []):
        if not RagChunk.objects.filter(pk=ref["id"], content_hash=ref["hash"]).exists():
            changed()

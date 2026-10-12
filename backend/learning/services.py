"""Deterministic learning reads and path generation; no model can mutate ratings."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, Max, Q
from django.utils import timezone

from account.models import AdminType
from knowledge.models import KnowledgeDependency, KnowledgePoint, ProblemKnowledge
from knowledge.services import knowledge_write
from submission.models import JudgeStatus, Submission
from utils.contract_api import ContractError, request_fingerprint, transaction_lock
from .models import (LearningPath, LearningPathStep, LearningRefreshRequest, ProblemKnowledgeRating,
                     StudentKnowledgeState, TeachingAccessEvent, TeachingClass)


def timestamp(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def fail(code, message, status=400, retryable=False):
    raise ContractError("LEARNING_" + code, message, status=status, retryable=retryable)


def effective_confidence(state):
    if not state.last_submission_time:
        return Decimal(0)
    age = max(0, (timezone.now() - state.last_submission_time).total_seconds())
    factor = Decimal(2) ** (-Decimal(str(age)) / Decimal(7 * 86400))
    return (Decimal(str(state.confidence)) * factor).quantize(Decimal(".001"), rounding=ROUND_HALF_UP)


def student_profile(user_id):
    states = StudentKnowledgeState.objects.filter(user_id=user_id, knowledge_point__status="active").select_related("knowledge_point").order_by("knowledge_point__code")
    rows = list(states[:100])
    return {"student_id": user_id, "algorithm_version": "elo-v1",
            "updated_time": timestamp(states.aggregate(latest=Max("updated_time"))["latest"]),
            "knowledge_states": [{"knowledge_code": x.knowledge_point.code, "name": x.knowledge_point.name,
                                  "rating": float(x.rating), "mastery_level": x.mastery_level,
                                  "attempt_count": x.attempt_count, "accepted_count": x.accepted_count,
                                  "recent_fail_count": x.recent_fail_count, "confidence": float(effective_confidence(x)),
                                  "last_submission_time": timestamp(x.last_submission_time)} for x in rows]}


def weakness(user_id, limit=5):
    if type(limit) is not int or not 1 <= limit <= 10:
        fail("INPUT_INVALID", "limit 必须为 1 到 10 的整数")
    states = list(StudentKnowledgeState.objects.filter(user_id=user_id, knowledge_point__status="active").select_related("knowledge_point"))
    ratings = {x.knowledge_point_id: x.rating for x in states}
    prerequisites = defaultdict(list)
    edges = KnowledgeDependency.objects.filter(relation_type="required", prerequisite__status="active", dependent__status="active")
    for prerequisite, dependent in edges.values_list("prerequisite_id", "dependent_id"):
        prerequisites[dependent].append(prerequisite)
    rows = []
    for state in states:
        reasons = []
        if state.rating < 1200:
            reasons.append("low_rating")
        if state.recent_fail_count >= 3:
            reasons.append("recent_failures")
        if state.attempt_count >= 3 and state.accepted_count / state.attempt_count < .4:
            reasons.append("low_acceptance")
        if any(ratings.get(pk, Decimal("1200")) < 1200 for pk in prerequisites[state.knowledge_point_id]):
            reasons.append("prerequisite_gap")
        confidence = effective_confidence(state)
        if confidence < Decimal(".3"):
            reasons.append("low_confidence")
        if reasons:
            rows.append((state.rating, state.knowledge_point.code, {"knowledge_code": state.knowledge_point.code,
                                                                    "name": state.knowledge_point.name, "rating": float(state.rating), "mastery_level": state.mastery_level,
                                                                    "confidence": float(confidence), "reason_codes": reasons}))
    return {"algorithm_version": "elo-v1", "generated_time": timestamp(timezone.now()),
            "weak_points": [row[2] for row in sorted(rows, key=lambda row: (row[0], row[1]))[:limit]]}


def authorize_class(actor, class_id, student_id=None, audit_reason="", request_id=""):
    code = "STUDENT_NOT_FOUND" if student_id is not None else "CLASS_NOT_FOUND"
    try:
        key = UUID(str(class_id))
    except (ValueError, TypeError, AttributeError):
        fail("INPUT_INVALID", "class_id 必须是 UUID")
    klass = TeachingClass.objects.filter(pk=key, status="active").first()
    if klass is None:
        fail(code, "对象不存在或不在授权范围", 404)
    authorized = klass.teachers.filter(teacher_id=actor.pk, teacher__is_disabled=False, status="active").exists()
    if not authorized:
        if actor.admin_type not in (AdminType.ADMIN, AdminType.SUPER_ADMIN) or not audit_reason.strip():
            fail(code, "对象不存在或不在授权范围", 404)
        if len(audit_reason) > 1000:
            fail("INPUT_INVALID", "审计理由过长")
    if student_id is not None and not klass.students.filter(student_id=student_id, student__is_disabled=False, status="active").exists():
        fail(code, "对象不存在或不在授权范围", 404)
    if not authorized:
        TeachingAccessEvent.objects.create(actor=actor, teaching_class=klass, student_id=student_id,
                                           reason=audit_reason.strip(), request_id=request_id)
    return klass


def class_stats(actor, class_id, audit_reason="", request_id=""):
    klass = authorize_class(actor, class_id, audit_reason=audit_reason, request_id=request_id)
    users = klass.students.filter(status="active", student__is_disabled=False).values_list("student_id", flat=True)
    rows = StudentKnowledgeState.objects.filter(user_id__in=users, knowledge_point__status="active").values("knowledge_point__code", "knowledge_point__name").annotate(
        student_count=Count("user_id"), average_rating=Avg("rating"),
        weak_count=Count("user_id", filter=Q(mastery_level="weak")), mastered_count=Count("user_id", filter=Q(mastery_level="mastered"))).order_by("knowledge_point__code")[:500]
    return {"class_id": str(klass.pk), "student_count": users.count(), "algorithm_version": "elo-v1",
            "generated_time": timestamp(timezone.now()), "knowledge_stats": [
                {"knowledge_code": row["knowledge_point__code"], "name": row["knowledge_point__name"],
                 "student_count": row["student_count"], "average_rating": float(row["average_rating"]),
                 "weak_count": row["weak_count"], "mastered_count": row["mastered_count"]} for row in rows]}


def path_data(path):
    target = path.target_knowledge
    steps = []
    for step in path.steps.select_related("knowledge_point", "problem"):
        problem = step.problem
        # Visibility can change after generation; never return hidden/contest problem metadata.
        if problem is not None and (not problem.visible or problem.contest_id is not None):
            problem = None
        steps.append({"order": step.step_order, "knowledge_code": step.knowledge_point.code,
                      "knowledge_name": step.knowledge_point.name, "problem_id": problem._id if problem else None,
                      "title": problem.title if problem else None, "problem_rating": float(step.problem_rating) if problem and step.problem_rating is not None else None,
                      "reason_code": step.reason_code, "reason_text": step.reason_text, "status": step.status})
    return {"path_id": str(path.pk), "algorithm_version": path.algorithm_version, "status": path.status,
            "target": {"knowledge_code": target.code, "name": target.name} if target else None,
            "steps": steps, "generated_time": timestamp(path.generated_time), "expires_time": timestamp(path.expires_time)}


def current_path(user_id):
    with transaction.atomic():
        transaction_lock("learning_path", user_id)
        LearningPath.objects.filter(user_id=user_id, status="active", expires_time__lte=timezone.now()).update(status="expired")
        path = LearningPath.objects.select_related("target_knowledge").filter(user_id=user_id, status="active").first()
        if path is None:
            fail("PATH_NOT_FOUND", "尚未生成活动学习路径", 404, retryable=True)
        return path_data(path)


def refresh_path(user_id, target_code=None, key=None):
    # Take the graph lock before the user lock, in the same order as knowledge writes.
    with knowledge_write():
        transaction_lock("learning_path", user_id)
        fingerprint = request_fingerprint({"target_knowledge_code": target_code})
        if key:
            previous = LearningRefreshRequest.objects.filter(user_id=user_id, key=key).first()
            if previous:
                if previous.fingerprint != fingerprint:
                    fail("REFRESH_CONFLICT", "幂等键已用于不同请求", 409)
                # Re-read visibility for replay; snapshot identity is stable, secret metadata is not.
                replay = dict(previous.response)
                from problem.models import Problem
                visible = set(Problem.objects.filter(contest__isnull=True, visible=True,
                                                     _id__in=[step["problem_id"] for step in replay["steps"] if step["problem_id"]]).values_list("_id", flat=True))
                replay["steps"] = [dict(step) for step in replay["steps"]]
                for step in replay["steps"]:
                    if step["problem_id"] and step["problem_id"] not in visible:
                        step.update(problem_id=None, title=None, problem_rating=None)
                return replay
        points = {x.pk: x for x in KnowledgePoint.objects.filter(status="active")}
        by_code = {x.code: x for x in points.values()}
        target = by_code.get(target_code) if target_code else None
        if target_code and target is None:
            fail("INPUT_INVALID", "目标知识点不可用")
        last = LearningPath.objects.filter(user_id=user_id).order_by("-generated_time").first()
        if last and (timezone.now() - last.generated_time).total_seconds() < getattr(settings, "LEARNING_REFRESH_INTERVAL", 10):
            fail("RATE_LIMITED", "刷新过于频繁，请稍后重试", 429, retryable=True)
        states = {x.knowledge_point_id: x for x in StudentKnowledgeState.objects.filter(user_id=user_id)}
        prerequisites = defaultdict(list)
        edges = KnowledgeDependency.objects.filter(relation_type="required", prerequisite_id__in=points, dependent_id__in=points)
        for pre, dep in edges.order_by("prerequisite__code").values_list("prerequisite_id", "dependent_id"):
            prerequisites[dep].append(pre)
        if target:
            roots = [target.pk]
        else:
            roots = sorted(points, key=lambda pk: (states[pk].rating if pk in states else Decimal("1200"), points[pk].level, points[pk].code))
        visited, visiting, ordered = set(), set(), []

        for root in roots:
            stack = [(root, False)]
            while stack:
                pk, expanded = stack.pop()
                if pk in visited:
                    continue
                if expanded:
                    visiting.remove(pk)
                    visited.add(pk)
                    state = states.get(pk)
                    if pk == (target.pk if target else None) or state is None or state.mastery_level != "mastered":
                        ordered.append(pk)
                else:
                    if pk in visiting:
                        fail("DEPENDENCY_NOT_READY", "知识依赖尚未就绪", 503, retryable=True)
                    visiting.add(pk)
                    stack.append((pk, True))
                    stack.extend((pre, False) for pre in reversed(prerequisites[pk]))
        accepted = set(Submission.objects.filter(user_id=user_id, result=JudgeStatus.ACCEPTED).values_list("problem_id", flat=True))
        mappings = list(ProblemKnowledge.objects.filter(knowledge_point_id__in=ordered, review_status="approved",
                                                        problem__contest__isnull=True, problem__visible=True).select_related("problem"))
        problem_ratings = {(x.problem_id, x.knowledge_point_id): x.rating for x in ProblemKnowledgeRating.objects.filter(knowledge_point_id__in=ordered)}
        candidates = defaultdict(list)
        for mapping in mappings:
            problem = mapping.problem
            if problem.pk in accepted or not problem.test_case_id or not problem.test_case_score or not problem.languages or (problem.spj and not problem.spj_compile_ok):
                continue
            rating = problem_ratings.get((problem.pk, mapping.knowledge_point_id), Decimal({"Low": "1000", "Mid": "1200", "High": "1500"}.get(problem.difficulty, "1200")))
            state = states.get(mapping.knowledge_point_id)
            student_rating = state.rating if state else Decimal("1200")
            # Avoid overwhelming the learner: choose the nearest problem at or below +200.
            if rating <= student_rating + 200:
                candidates[mapping.knowledge_point_id].append((abs(rating - student_rating), problem._id, problem, rating))
        LearningPath.objects.filter(user_id=user_id, status="active").update(status="superseded")
        path = LearningPath.objects.create(user_id=user_id, target_knowledge=target, expires_time=timezone.now()+timedelta(days=7),
                                           input_snapshot={"ratings": {points[pk].code: str(x.rating) for pk, x in states.items() if pk in points}},
                                           reason_summary={"target": target_code, "prerequisites_first": True, "max_steps": 5})
        used = set()
        for pk in ordered[:5]:
            options = [x for x in candidates[pk] if x[2].pk not in used]
            chosen = min(options, key=lambda x: (x[0], x[1])) if options else None
            if chosen:
                used.add(chosen[2].pk)
            LearningPathStep.objects.create(learning_path=path, step_order=path.steps.count()+1, knowledge_point=points[pk],
                                            problem=chosen[2] if chosen else None, problem_rating=chosen[3] if chosen else None,
                                            reason_code="prerequisite_weak" if target and pk != target.pk else "target_practice" if target else "weakness_practice",
                                            reason_text="前置知识掌握不足" if target and pk != target.pk else "巩固当前知识点" if chosen else "先复习知识点，暂无合适的可判题练习")
        result = path_data(path)
        if key:
            LearningRefreshRequest.objects.create(user_id=user_id, key=key, fingerprint=fingerprint, response=result)
        return result

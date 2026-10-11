"""Decimal Elo with durable input snapshots and deterministic rejudge replay."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP, localcontext
import logging

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from account.models import User
from knowledge.models import ProblemKnowledge
from knowledge.services import knowledge_write
from submission.models import JudgeStatus, Submission
from utils.contract_api import request_fingerprint, transaction_lock
from .models import (LearningPath, LearningSubmissionEvent, ProblemKnowledgeRating,
                     RatingHistory, StudentKnowledgeState)

logger = logging.getLogger(__name__)
D = Decimal
Q4, Q6 = D(".0001"), D(".000001")
TERMINAL = {-2, -1, 0, 1, 2, 3, 4, 8}


def score_for(result, rule_type, score, total):
    if result not in TERMINAL or result == JudgeStatus.COMPILE_ERROR:
        return None
    if rule_type == "OI" and total > 0:
        try:
            number = D(str(score)) / D(total)
            return min(D(1), max(D(0), number)) if number.is_finite() else None
        except (ValueError, TypeError, ArithmeticError):
            return None
    if result == JudgeStatus.ACCEPTED:
        return D(1)
    if result in (JudgeStatus.CPU_TIME_LIMIT_EXCEEDED, JudgeStatus.REAL_TIME_LIMIT_EXCEEDED,
                  JudgeStatus.MEMORY_LIMIT_EXCEEDED, JudgeStatus.RUNTIME_ERROR):
        return D(".1")
    return D(0)


def dispatch_event(event_id):
    try:
        from .tasks import process_learning_event
        process_learning_event.send(event_id)
    except Exception as exc:
        # The outbox is authoritative and can be re-delivered without losing a judged result.
        logger.warning("learning_enqueue_failed event=%s type=%s", event_id, type(exc).__name__)
        LearningSubmissionEvent.objects.filter(pk=event_id, status="pending").update(error_code="LEARNING_QUEUE_UNAVAILABLE")


def capture_submission(submission):
    if submission.contest_id is not None or submission.problem.contest_id is not None:
        return None
    if not User.objects.filter(pk=submission.user_id).exists():
        return None
    # Fresh pending/judging requests need no learning snapshot or graph lock.
    if submission.result not in TERMINAL and not LearningSubmissionEvent.objects.filter(submission_id=submission.pk).exists():
        return None
    with knowledge_write():
        transaction_lock("learning_rating", "global")
        submission = Submission.objects.select_related("problem").get(pk=submission.pk)
        if submission.contest_id is not None or submission.problem.contest_id is not None:
            return None
        event = LearningSubmissionEvent.objects.filter(submission=submission).first()
        if submission.result not in TERMINAL and event is None:
            return None
        actual = score_for(submission.result, submission.problem.rule_type,
                           (submission.statistic_info or {}).get("score", 0), submission.problem.total_score)
        signature = {"result": submission.result, "actual": str(actual) if actual is not None else None}
        source = {"result": submission.result, "score": (submission.statistic_info or {}).get("score", 0),
                  "rule_type": submission.problem.rule_type, "total_score": submission.problem.total_score}
        fingerprint = request_fingerprint(signature)
        if event and event.fingerprint == fingerprint and event.payload.get("source", source) == source:
            if event.payload.get("source") != source:
                event.payload = {**event.payload, "source": source}
                event.save(update_fields=["payload", "updated_time"])
            return event
        if event:
            payload = dict(event.payload)
            revisions = list(payload.get("previous_results", []))
            revisions.append({"revision": event.revision, "result": payload["result"], "actual": payload["actual"],
                              "source": payload.get("source"), "captured_time": payload.get("captured_time")})
            payload.update(signature, source=source, captured_time=timezone.now().isoformat(), previous_results=revisions)
            event.payload, event.fingerprint = payload, fingerprint
            event.revision += 1
            event.status, event.error_code = "pending", ""
            event.save()
        else:
            mappings = list(ProblemKnowledge.objects.filter(problem=submission.problem,
                                                            knowledge_point__status="active", review_status="approved").select_related("knowledge_point"))
            weights = sum((mapping.weight for mapping in mappings), D(0))
            snapshot = []
            for mapping in mappings:
                initial_rating = D({"Low": "1000", "Mid": "1200", "High": "1500"}.get(submission.problem.difficulty, "1200"))
                rating, _ = ProblemKnowledgeRating.objects.get_or_create(
                    problem=submission.problem, knowledge_point=mapping.knowledge_point,
                    defaults={"rating": initial_rating})
                snapshot.append({"knowledge_id": mapping.knowledge_point_id,
                                 "knowledge_code": mapping.knowledge_point.code,
                                 "weight": str(mapping.weight / weights), "problem_rating": str(rating.rating)})
            event = LearningSubmissionEvent.objects.create(
                submission=submission, user_id=submission.user_id, fingerprint=fingerprint,
                payload={**signature, "source": source, "captured_time": timezone.now().isoformat(), "problem_id": submission.problem_id,
                         "submission_time": submission.create_time.isoformat(), "mappings": snapshot, "previous_results": []})
        transaction.on_commit(lambda pk=event.pk: dispatch_event(pk))
        return event


def mastery(rating, failures):
    levels = ["weak", "learning", "stable", "mastered"]
    level = 3 if rating >= 1500 else 2 if rating >= 1200 else 1 if rating >= 1000 else 0
    if failures >= 3:
        level = max(0, level - 1)
    return levels[level]


def process_event(event_id):
    with knowledge_write():
        transaction_lock("learning_rating", "global")
        event = LearningSubmissionEvent.objects.select_for_update().filter(pk=event_id).first()
        if event is None or (event.status == "processed" and event.processed_revision == event.revision):
            return
        replay_user(event.user_id, locked=True)


def replay_user(user_id, locked=False):
    if not locked:
        with knowledge_write():
            transaction_lock("learning_rating", "global")
            return replay_user(user_id, locked=True)
    events = list(LearningSubmissionEvent.objects.filter(user_id=user_id).select_related("submission").order_by("submission__create_time", "submission_id"))
    states, repetition = {}, defaultdict(int)
    history = []
    pairs = set(RatingHistory.objects.filter(user_id=user_id).values_list("problem_id", "knowledge_point_id"))
    with localcontext() as ctx:
        ctx.prec = 32
        for event in events:
            payload = event.payload
            if payload["actual"] is None:
                continue
            actual = D(payload["actual"])
            problem_id = payload["problem_id"]
            decay = D(1) / D(repetition[problem_id] + 1).sqrt()
            repetition[problem_id] += 1
            for mapping in payload["mappings"]:
                pk = mapping["knowledge_id"]
                state = states.setdefault(pk, {"rating": D(1200), "count": 0, "accepted": 0, "recent": [], "time": None})
                problem_rating, weight = D(mapping["problem_rating"]), D(mapping["weight"])
                old = state["rating"]
                expected = D(1) / (D(1) + D(10) ** ((problem_rating - old) / D(400)))
                new = max(D(0), old + D(32) * weight * decay * (actual - expected)).quantize(Q4, rounding=ROUND_HALF_UP)
                state.update(rating=new, count=state["count"]+1, accepted=state["accepted"]+int(payload["result"] == 0), time=event.submission.create_time)
                state["recent"] = (state["recent"] + [payload["result"] != 0])[-5:]
                pairs.add((problem_id, pk))
                history.append(RatingHistory(user_id=user_id, knowledge_point_id=pk, problem_id=problem_id,
                                             submission_id=event.submission_id, old_rating=old, new_rating=new, delta=new-old,
                                             problem_rating=problem_rating, expected_score=expected.quantize(Q6, rounding=ROUND_HALF_UP),
                                             actual_score=actual.quantize(Q6, rounding=ROUND_HALF_UP), result=payload["result"], result_weight=D(1),
                                             calculation_detail={"k": "32", "mapping_weight": str(weight), "repeat_decay": str(decay), "input_revision": event.revision}))
    RatingHistory.objects.filter(user_id=user_id).delete()
    RatingHistory.objects.bulk_create(history)
    StudentKnowledgeState.objects.filter(user_id=user_id).exclude(knowledge_point_id__in=states).delete()
    # Replays remain serialized by the existing graph/rating locks. Batch writes
    # reduce lock hold time without changing snapshot or cross-user count semantics.
    existing_states = {row.knowledge_point_id: row for row in StudentKnowledgeState.objects.filter(user_id=user_id)}
    created_states, changed_states = [], []
    updated_time = timezone.now()
    state_fields = ["rating", "mastery_level", "attempt_count", "accepted_count", "recent_fail_count",
                    "confidence", "last_submission_time", "algorithm_version", "updated_time"]
    for pk, state in states.items():
        failures = sum(state["recent"])
        row = existing_states.get(pk) or StudentKnowledgeState(user_id=user_id, knowledge_point_id=pk)
        values = [state["rating"], mastery(state["rating"], failures), state["count"], state["accepted"], failures,
                  (D(state["count"])/(D(state["count"])+D(10))).quantize(D(".001"), rounding=ROUND_HALF_UP),
                  state["time"], "elo-v1", updated_time]
        for field, value in zip(state_fields, values):
            setattr(row, field, value)
        (changed_states if row.pk else created_states).append(row)
    StudentKnowledgeState.objects.bulk_create(created_states)
    StudentKnowledgeState.objects.bulk_update(changed_states, state_fields)
    if pairs:
        scope = Q()
        for problem_id, pk in sorted(pairs):
            scope |= Q(problem_id=problem_id, knowledge_point_id=pk)
        counts = {(row["problem_id"], row["knowledge_point_id"]): row
                  for row in RatingHistory.objects.filter(scope).values("problem_id", "knowledge_point_id").annotate(
                      total=Count("pk"), accepted=Count("pk", filter=Q(result=0)))}
        problem_ratings = list(ProblemKnowledgeRating.objects.filter(scope))
        for row in problem_ratings:
            count = counts.get((row.problem_id, row.knowledge_point_id), {"total": 0, "accepted": 0})
            row.attempt_count, row.accepted_count = count["total"], count["accepted"]
            row.confidence = (D(count["total"])/(D(count["total"])+D(10))).quantize(D(".001"), rounding=ROUND_HALF_UP)
            row.updated_time = updated_time
        ProblemKnowledgeRating.objects.bulk_update(problem_ratings, ["attempt_count", "accepted_count", "confidence", "updated_time"])
    transaction_lock("learning_path", user_id)
    # Progress and rating must use the same durable revision, even if capture of
    # a newer live verdict failed and recovery has not reconciled it yet.
    accepted = {event.payload["problem_id"] for event in events
                if event.payload["result"] == JudgeStatus.ACCEPTED and event.payload["actual"] is not None}
    path = LearningPath.objects.filter(user_id=user_id).order_by("-generated_time", "-pk").first()
    if path and path.status in ("active", "completed"):
        path.steps.filter(problem_id__in=accepted).update(status="completed")
        path.steps.filter(status="completed", problem_id__isnull=False).exclude(problem_id__in=accepted).update(status="pending")
        if path.steps.exists() and not path.steps.exclude(status="completed").exists():
            path.status = "completed"
        elif path.expires_time is not None and path.expires_time <= timezone.now():
            path.status = "expired"
        elif path.steps.exclude(knowledge_point__status="active").exists() or (
                path.target_knowledge_id and path.target_knowledge.status != "active"):
            path.status = "superseded"
        else:
            path.status = "active"
        path.save(update_fields=["status"])
    for event in events:
        event.status, event.processed_revision, event.error_code = "processed", event.revision, ""
    LearningSubmissionEvent.objects.bulk_update(events, ["status", "processed_revision", "error_code"])
    return len(history)

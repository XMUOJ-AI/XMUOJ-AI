#!/usr/bin/env python3
"""Bounded concurrent judge-result/learning DB benchmark; ONLY disposable xmuoj_h1."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import math
import os
import platform
from pathlib import Path
from queue import Queue
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "oj.settings")
import django

django.setup()
from django.conf import settings
from django.core.management import call_command
from django.db import connection, connections, transaction
from django.db.models import Count, F, Q
from django.test import override_settings
from django.utils import timezone
from account.models import User, UserProfile
from judge.dispatcher import JudgeDispatcher
from judge.tasks import retry_learning_capture
from learning.signals import LearningCaptureError
from knowledge.models import KnowledgePoint, ProblemKnowledge
from knowledge.services import KNOWLEDGE_WRITE_LOCK
from learning import ratings
from learning.models import LearningSubmissionEvent, ProblemKnowledgeRating, RatingHistory, StudentKnowledgeState
from problem.models import Problem
from submission.models import JudgeStatus, Submission


def percentile(values, fraction):
    values = sorted(values)
    return round(values[max(0, math.ceil(len(values) * fraction) - 1)] * 1000, 3) if values else None


def distribution(values):
    return {"samples": len(values), "p50_ms": percentile(values, .5), "p95_ms": percentile(values, .95),
            "p99_ms": percentile(values, .99), "max_ms": percentile(values, 1)}


def fingerprint(queryset):
    return hashlib.sha256(json.dumps(list(queryset), sort_keys=True, default=str).encode()).hexdigest()


def seed(count, history):
    if User.objects.exists():
        raise SystemExit("Nonempty benchmark database; pass --reset to reset ONLY xmuoj_h1")
    admin = User.objects.create(username="h1_seed_admin")
    users = User.objects.bulk_create([User(username=f"h1_student_{index:04}") for index in range(count)])
    UserProfile.objects.bulk_create([UserProfile(user=user) for user in users])
    points = KnowledgePoint.objects.bulk_create([
        KnowledgePoint(code=f"h1_k{index}", name=f"H1 knowledge {index}", normalized_name=f"h1 knowledge {index}",
                       category="algorithm", level=1, status="active", created_by=admin) for index in range(2)])
    problems = Problem.objects.bulk_create([
        Problem(_id=f"H1P{index}", title=f"H1 problem {index}", description="benchmark", input_description="",
                output_description="", samples=[], test_case_id="h1", test_case_score=[{"score": 100}],
                languages=["Python3"], template={}, time_limit=1000, memory_limit=128, rule_type="ACM",
                difficulty="Low", visible=True, created_by=admin) for index in range(4)])
    ProblemKnowledge.objects.bulk_create([
        ProblemKnowledge(problem=problem, knowledge_point=point, role="primary" if index == 0 else "secondary",
                         weight=Decimal(".5"), review_status="approved", reviewed_by=admin)
        for problem in problems for index, point in enumerate(points)])
    submissions = Submission.objects.bulk_create([
        Submission(id=f"h1_history_{user.pk}_{index:04}", problem=problems[index % len(problems)], user_id=user.pk,
                   username=user.username, code="print(1)", language="Python3", result=0 if index % 3 else -1)
        for user in users for index in range(history)])
    base_time = timezone.now() - timedelta(days=1)
    for index, submission in enumerate(submissions):
        submission.create_time = base_time + timedelta(seconds=index % history)
    Submission.objects.bulk_update(submissions, ["create_time"])
    # Initialize the legacy profile JSON too: real histories already have these
    # entries, and the verdict writer only refreshes the current problem's entry.
    history_status = {}
    for submission in submissions[:history]:
        previous = history_status.get(str(submission.problem_id))
        if previous is None or previous["status"] != JudgeStatus.ACCEPTED:
            history_status[str(submission.problem_id)] = {"status": submission.result, "_id": submission.problem._id}
    profiles = list(UserProfile.objects.filter(user_id__in=[user.pk for user in users]))
    for profile in profiles:
        profile.acm_problems_status = {"problems": deepcopy(history_status)}
        profile.submission_number = history
        profile.accepted_number = sum(value["status"] == 0 for value in history_status.values())
    UserProfile.objects.bulk_update(profiles, ["acm_problems_status", "submission_number", "accepted_number"])
    # Bulk historical fixtures use templates from real capture; only the burst is measured.
    # Avoid spending minutes serially replaying the same setup plumbing for 4,800 rows.
    with patch("learning.ratings.dispatch_event", lambda event_id: None):
        templates, events = {}, []
        for submission in submissions:
            key = (submission.problem_id, submission.result)
            if key not in templates:
                templates[key] = ratings.capture_submission(submission)
            else:
                source = templates[key]
                payload = deepcopy(source.payload)
                payload["submission_time"] = submission.create_time.isoformat()
                events.append(LearningSubmissionEvent(submission=submission, user_id=submission.user_id,
                                                      fingerprint=source.fingerprint, payload=payload))
        LearningSubmissionEvent.objects.bulk_create(events)
        print(f"Historical fixtures captured; replaying {count} initial profiles", flush=True)
        for index, user in enumerate(users, 1):
            ratings.replay_user(user.pk)
            if index % 60 == 0:
                print(f"Initial profiles: {index}/{count}", flush=True)
    print(f"Seeded {count} users with {history} durable historical submissions each", flush=True)
    return users, problems


def scenario(users, problems, number, judge_workers, learning_workers):
    cohort = users[:number]
    burst = Submission.objects.bulk_create([
        Submission(id=f"h1_burst_{number}_{user.pk}", user_id=user.pk, username=user.username,
                   problem=problems[index % len(problems)], code="print(1)", language="Python3", result=JudgeStatus.JUDGING)
        for index, user in enumerate(cohort)])
    history_counts = [LearningSubmissionEvent.objects.filter(user=user).count() for user in cohort]
    metrics = {key: [] for key in ("commit", "queue", "total", "advisory", "row_lock", "learning",
                                   "knowledge_lock", "rating_lock", "path_lock")}
    rating_lock_key = int.from_bytes(hashlib.sha256(b"learning_rating:global").digest()[:8], "big", signed=True)
    errors, sql_errors, lock_samples, sql_statements, retries = [], [], [], [], []
    commits, processed = {}, {}
    event_users = {}
    learning_queue = Queue()
    stopped = threading.Event()
    burst_started = time.perf_counter()

    def instrument(execute, sql, params, many, context):
        sql_statements.append(1)
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        except Exception as exc:
            sql_errors.append(getattr(exc.__cause__, "pgcode", None) or type(exc).__name__)
            raise
        finally:
            elapsed = time.perf_counter() - start
            if "pg_advisory_xact_lock" in sql:
                metrics["advisory"].append(elapsed)
                key = "knowledge_lock" if params[0] == KNOWLEDGE_WRITE_LOCK else "rating_lock" if params[0] == rating_lock_key else "path_lock"
                metrics[key].append(elapsed)
            elif "FOR UPDATE" in sql:
                metrics["row_lock"].append(elapsed)

    @contextmanager
    def worker_connection(role):
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET application_name = %s", ["h1_" + role])
            with connection.execute_wrapper(instrument):
                yield
        finally:
            connections.close_all()

    def collect_processed(user_id):
        event_id = event_users.get(user_id)
        if event_id and LearningSubmissionEvent.objects.filter(pk=event_id, status="processed", processed_revision=F("revision")).exists():
            processed.setdefault(user_id, time.perf_counter())

    def learning_worker():
        with worker_connection("learning"):
            while True:
                item = learning_queue.get()
                try:
                    if item is None:
                        return
                    kind, identity, user_id = item
                    start = time.perf_counter()
                    for attempt in range(4):
                        try:
                            if kind == "replay":
                                ratings.replay_user(user_id)
                            else:
                                ratings.process_event(identity)
                            break
                        except Exception:
                            if attempt == 3:
                                raise
                            retries.append({"role": "learning", "attempt": attempt + 1})
                            time.sleep(2 ** attempt)
                    metrics["learning"].append(time.perf_counter() - start)
                    collect_processed(user_id)
                except Exception as exc:
                    errors.append({"role": "learning", "type": type(exc).__name__})
                finally:
                    learning_queue.task_done()

    def enqueue(event_id):
        user_id = LearningSubmissionEvent.objects.values_list("user_id", flat=True).get(pk=event_id)
        event_users[user_id] = event_id
        learning_queue.put(("event", event_id, user_id))

    def judge_result(submission_id):
        start = time.perf_counter()
        metrics["queue"].append(start - burst_started)
        try:
            with worker_connection("judge"):
                # Same transaction boundary as JudgeDispatcher._judge after a real verdict is returned.
                # Excludes sandbox/network work; calls real outbox signal and legacy aggregate writer.
                for attempt in range(4):
                    try:
                        submission = Submission.objects.select_related("problem").get(pk=submission_id)
                        dispatcher = JudgeDispatcher.__new__(JudgeDispatcher)
                        dispatcher.submission, dispatcher.problem, dispatcher.contest_id = submission, submission.problem, None
                        with transaction.atomic():
                            submission.result = JudgeStatus.ACCEPTED
                            submission.statistic_info = {"score": 100, "time_cost": 1, "memory_cost": 1024}
                            submission.save()
                            dispatcher.update_problem_status()
                        break
                    except LearningCaptureError as error:
                        if not retry_learning_capture(attempt, error):
                            raise
                        retries.append({"role": "judge", "attempt": attempt + 1})
                        time.sleep(2 ** attempt)
                commits[submission.user_id] = time.perf_counter()
                metrics["commit"].append(commits[submission.user_id] - start)
                metrics["total"].append(commits[submission.user_id] - burst_started)
        except Exception as exc:
            errors.append({"role": "judge", "type": type(exc).__name__})

    def monitor_locks():
        connections.close_all()
        try:
            while not stopped.wait(.02):
                with connection.cursor() as cursor:
                    cursor.execute("SELECT wait_event, count(*) FROM pg_stat_activity WHERE datname=current_database() "
                                   "AND application_name LIKE 'h1_%%' AND wait_event_type='Lock' GROUP BY wait_event")
                    lock_samples.append((time.perf_counter(), dict(cursor.fetchall())))
        finally:
            connections.close_all()

    monitor = threading.Thread(target=monitor_locks, daemon=True)
    monitor.start()
    with override_settings(DEBUG=False), patch("learning.ratings.dispatch_event", enqueue):
        with ThreadPoolExecutor(max_workers=learning_workers) as learning_pool:
            futures = [learning_pool.submit(learning_worker) for _ in range(learning_workers)]
            # Explicit full-profile replays overlap the incoming verdict burst.
            for user in cohort:
                learning_queue.put(("replay", None, user.pk))
            with ThreadPoolExecutor(max_workers=judge_workers) as judge_pool:
                list(judge_pool.map(judge_result, [submission.pk for submission in burst]))
            learning_queue.join()
            for _ in futures:
                learning_queue.put(None)
            for future in futures:
                future.result()
    elapsed = time.perf_counter() - burst_started
    stopped.set()
    monitor.join()
    user_ids = [user.pk for user in cohort]
    events = LearningSubmissionEvent.objects.filter(user_id__in=user_ids)
    states = StudentKnowledgeState.objects.filter(user_id__in=user_ids).order_by("user_id", "knowledge_point_id")
    state_fields = ("user_id", "knowledge_point_id", "rating", "attempt_count", "accepted_count", "recent_fail_count", "confidence")
    before = fingerprint(states.values(*state_fields))
    terminal = Submission.objects.filter(user_id__in=user_ids, result=JudgeStatus.ACCEPTED)
    expected_count = Submission.objects.filter(user_id__in=user_ids).count()
    counts_correct = states.count() == len(cohort) * 2 and all(
        state.attempt_count == events.filter(user_id=state.user_id).count()
        and state.accepted_count == terminal.filter(user_id=state.user_id).count() for state in states)
    problem_counts_correct = True
    for problem in problems:
        actual = Submission.objects.filter(problem=problem).exclude(result__in=(6, 7)).aggregate(
            attempts=Count("pk"), accepted=Count("pk", filter=Q(result=0)))
        problem.refresh_from_db()
        problem_counts_correct &= (problem.submission_number == actual["attempts"] and problem.accepted_number == actual["accepted"])
    ratings_correct = ProblemKnowledgeRating.objects.count() == len(problems) * 2
    for rating in ProblemKnowledgeRating.objects.all():
        actual = RatingHistory.objects.filter(problem_id=rating.problem_id, knowledge_point_id=rating.knowledge_point_id).aggregate(
            attempts=Count("pk"), accepted=Count("pk", filter=Q(result=0)))
        ratings_correct &= (rating.attempt_count == actual["attempts"] and rating.accepted_count == actual["accepted"])
    user_counts_correct = True
    for profile in UserProfile.objects.filter(user_id__in=user_ids):
        finished = Submission.objects.filter(user_id=profile.user_id).exclude(result__in=(6, 7))
        solved = finished.filter(result=0).values("problem_id").distinct().count()
        user_counts_correct &= profile.submission_number == finished.count() and profile.accepted_number == solved
    checks = {"committed_burst": len(commits) == number, "observed_processed_burst": len(processed) == number,
              "all_terminal_events_exist": events.count() == expected_count,
              "all_revisions_processed": not events.exclude(status="processed", processed_revision=F("revision")).exists(),
              "history_count": RatingHistory.objects.filter(user_id__in=user_ids).count() == expected_count * 2,
              "student_counts": counts_correct, "legacy_user_counts": user_counts_correct,
              "legacy_problem_counts": problem_counts_correct, "problem_rating_counts": ratings_correct}
    # Replay independently of measured queues to ensure concurrency did not corrupt final Elo values.
    for user in cohort:
        ratings.replay_user(user.pk)
    checks["deterministic_replay"] = before == fingerprint(states.values(*state_fields))
    profile_lag = [max(0, processed[user_id] - committed) for user_id, committed in commits.items() if user_id in processed]
    profile_total = [finished - burst_started for finished in processed.values()]
    sampled_wait = sum((current[0] - previous[0]) * sum(previous[1].values()) for previous, current in zip(lock_samples, lock_samples[1:]))
    result = {"students": number, "history_before_burst": {"min": min(history_counts), "max": max(history_counts)},
              "judge_threads": judge_workers, "learning_threads": learning_workers, "elapsed_s": round(elapsed, 3),
              "terminal_execution": distribution(metrics["commit"]), "terminal_queue": distribution(metrics["queue"]),
              "terminal_from_burst": distribution(metrics["total"]), "profile_from_commit": distribution(profile_lag),
              "profile_from_burst": distribution(profile_total), "learning_job": distribution(metrics["learning"]),
              "advisory_lock_query": distribution(metrics["advisory"]), "row_lock_query": distribution(metrics["row_lock"]),
              "knowledge_graph_lock_query": distribution(metrics["knowledge_lock"]),
              "learning_global_lock_query": distribution(metrics["rating_lock"]),
              "learning_path_lock_query": distribution(metrics["path_lock"]),
              "postgres_lock_sampling": {"interval_ms": 20, "samples": len(lock_samples),
                                         "max_waiters": max((sum(sample[1].values()) for sample in lock_samples), default=0),
                                         "approx_session_wait_ms": round(sampled_wait * 1000, 3),
                                         "events_seen": dict(Counter(event for _, rows in lock_samples for event in rows))},
              "sql_statement_count": len(sql_statements),
              "retries": retries, "errors": errors, "sql_error_codes": dict(Counter(sql_errors)), "consistency": checks}
    result["suggested_local_slo"] = {"terminal_from_burst_p95_le_1000ms": (result["terminal_from_burst"]["p95_ms"] or float("inf")) <= 1000,
                                     "profile_from_burst_p95_le_30000ms": (result["profile_from_burst"]["p95_ms"] or float("inf")) <= 30000}
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[60, 120, 240])
    parser.add_argument("--history", type=int, default=20)
    parser.add_argument("--judge-workers", type=int, default=4)
    parser.add_argument("--learning-workers", type=int, default=4)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if settings.DATABASES["default"]["NAME"] != "xmuoj_h1" or connection.vendor != "postgresql":
        raise SystemExit("Refusing any database except disposable PostgreSQL xmuoj_h1")
    if min(args.sizes + [args.history, args.judge_workers, args.learning_workers]) < 1:
        raise SystemExit("All sizes and worker counts must be positive")
    if args.judge_workers + args.learning_workers > 24:
        raise SystemExit("Bounded benchmark allows at most 24 total worker connections")
    if args.reset:
        call_command("flush", interactive=False, verbosity=0)
    with override_settings(DEBUG=False):
        users, problems = seed(max(args.sizes), args.history)
    scope = ("PostgreSQL real terminal transaction + outbox + profile replay; local bounded queues; "
             "excludes HTTP, sandbox, network and actual Dramatiq/Redis transport")
    with connection.cursor() as cursor:
        cursor.execute("SELECT version()")
        postgres_version = cursor.fetchone()[0]
    source_files = ["backend/learning/ratings.py", "backend/learning/signals.py", "backend/judge/dispatcher.py", "backend/judge/tasks.py",
                    "backend/submission/models.py", "tools/benchmark_learning.py"]
    report = {"database": "xmuoj_h1", "scope": scope,
              "started_at": timezone.now().isoformat(), "python": platform.python_version(), "postgres": postgres_version,
              "source_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in source_files},
              "slo_note": "Suggested local pilot SLO, not a production commitment; queue time is included",
              "scenarios": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for number in args.sizes:
        report["scenarios"].append(scenario(users, problems, number, args.judge_workers, args.learning_workers))
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if any(row["errors"] or not all(row["consistency"].values()) for row in report["scenarios"]):
        raise SystemExit("Benchmark detected errors or consistency failures; see saved evidence")


if __name__ == "__main__":
    main()

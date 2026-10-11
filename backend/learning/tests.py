import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import quote

from django.db import close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings

from account.models import User
from knowledge.models import KnowledgeDependency, KnowledgePoint, ProblemKnowledge
from knowledge.tests import make_point, make_problem, make_user
from submission.models import Submission
from . import ratings, services
from .models import (LearningPath, LearningRefreshRequest, LearningSubmissionEvent, ProblemKnowledgeRating,
                     RatingHistory, StudentKnowledgeState, TeachingAccessEvent, TeachingClass,
                     TeachingClassStudent, TeachingClassTeacher)


class LearningFixture:
    def setUp(self):
        self.author = make_user("learning-admin")
        self.student = User.objects.create(username="learning-student")
        self.teacher = User.objects.create(username="learning-teacher")
        self.other = User.objects.create(username="learning-other")
        self.point = make_point("bfs", self.author)
        self.pre = make_point("queue", self.author)
        self.problem = make_problem(self.author, "LEARN1")
        self.problem.test_case_score = [{"input_name": "1.in", "output_name": "1.out", "score": 100}]
        self.problem.save()
        ProblemKnowledge.objects.create(problem=self.problem, knowledge_point=self.point,
                                        role="primary", weight=Decimal("1"), reviewed_by=self.author)
        self.client.force_login(self.student)

    def submit(self, result=0, problem=None):
        with patch("learning.ratings.dispatch_event"):
            return Submission.objects.create(user_id=self.student.pk, username=self.student.username,
                                             problem=problem or self.problem, code="PRIVATE-SOURCE-CODE", language="Python3", result=result)

    def call(self, method, path, data=None, expected=200, **headers):
        response = getattr(self.client, method)("/api/"+path, data=json.dumps(data) if data is not None else None,
                                                content_type="application/json", **headers)
        self.assertEqual(response.status_code, expected, response.content)
        self.assertEqual(response["X-API-Version"], "1.0.0")
        return response.json()


@override_settings(LEARNING_REFRESH_INTERVAL=0)
class LearningAPITests(LearningFixture, TestCase):
    def test_empty_profile_and_no_path(self):
        data = self.call("get", "learning/profile")["data"]
        self.assertEqual(data["knowledge_states"], [])
        self.assertIsNone(data["updated_time"])
        self.call("get", "recommendation/path", expected=404)
        self.call("get", "learning/weakness?limit=0", expected=400)
        self.call("get", "learning/weakness?limit=11", expected=400)
        self.call("get", "learning/profile?student_id=2", expected=400)

    def test_repeated_query_parameters_are_rejected(self):
        self.call("get", "learning/weakness?limit=1&limit=2", expected=400)
        class_id = "2caf14d0-8fc8-4994-a637-d8a82baf79bc"
        query = f"?class_id={class_id}&class_id={class_id}"
        self.call("get", "admin/learning/class/knowledge-stats"+query, expected=400)
        self.call("get", f"admin/learning/student/{self.student.pk}/profile"+query, expected=400)

    def test_anonymous_appkey_csrf_null_unknown(self):
        self.client.logout()
        self.call("get", "learning/profile", expected=401)
        self.author.open_api, self.author.open_api_appkey = True, "learning-key"
        self.author.save()
        self.call("get", "learning/profile", expected=401, HTTP_APPKEY="learning-key")
        self.client.force_login(self.student)
        for data in ([], {"user_id": self.other.pk}, {"target_knowledge_code": "BAD"}):
            self.call("post", "recommendation/refresh", data, expected=400)
        response = self.client.post("/api/recommendation/refresh", "null", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.student)
        self.assertEqual(client.post("/api/recommendation/refresh", "{}", content_type="application/json").status_code, 403)
        token = "b" * 32
        client.cookies["csrftoken"] = token
        response = client.post("/api/recommendation/refresh", "{}", content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200, response.content)

    def test_refresh_replay_conflict_and_single_active_path(self):
        first = self.call("post", "recommendation/refresh", {}, HTTP_IDEMPOTENCY_KEY="same")["data"]
        self.assertIsNone(first["target"])
        replay = self.call("post", "recommendation/refresh", {"target_knowledge_code": None}, HTTP_IDEMPOTENCY_KEY="same")["data"]
        self.assertEqual(first, replay)
        self.assertEqual(LearningPath.objects.count(), 1)
        self.call("post", "recommendation/refresh", {"target_knowledge_code": "bfs"}, expected=409, HTTP_IDEMPOTENCY_KEY="same")
        self.call("post", "recommendation/refresh", {}, expected=400, HTTP_IDEMPOTENCY_KEY="bad key")
        second = self.call("post", "recommendation/refresh", {"target_knowledge_code": "bfs"})["data"]
        self.assertNotEqual(first["path_id"], second["path_id"])
        self.assertEqual(LearningPath.objects.filter(status="active").count(), 1)
        self.assertEqual(LearningPath.objects.filter(status="superseded").count(), 1)

    @override_settings(LEARNING_REFRESH_INTERVAL=10)
    def test_refresh_rate_limit_and_replay_exemption(self):
        self.call("post", "recommendation/refresh", {}, HTTP_IDEMPOTENCY_KEY="replay")
        self.call("post", "recommendation/refresh", {}, HTTP_IDEMPOTENCY_KEY="replay")
        response = self.client.post("/api/recommendation/refresh", "{}", content_type="application/json")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "10")

    def test_prerequisites_and_visibility_rechecked_on_read_and_replay(self):
        KnowledgeDependency.objects.create(prerequisite=self.pre, dependent=self.point, relation_type="required", weight="1", created_by=self.author)
        first = self.call("post", "recommendation/refresh", {"target_knowledge_code": "bfs"}, HTTP_IDEMPOTENCY_KEY="visible")["data"]
        self.assertEqual([x["knowledge_code"] for x in first["steps"]], ["queue", "bfs"])
        self.assertEqual(first["steps"][1]["problem_id"], "LEARN1")
        self.problem.visible = False
        self.problem.save()
        for data in (services.current_path(self.student.pk), services.refresh_path(self.student.pk, "bfs", "visible")):
            self.assertIsNone(data["steps"][1]["problem_id"])
            self.assertIsNone(data["steps"][1]["title"])

    def test_deep_prerequisite_chain_does_not_depend_on_python_recursion_limit(self):
        points = KnowledgePoint.objects.bulk_create([
            KnowledgePoint(code=f"deep{i:04d}", name=f"Deep {i}", normalized_name=f"deep {i}",
                           category="algorithm", level=2, status="active", created_by=self.author) for i in range(1005)])
        KnowledgeDependency.objects.bulk_create([
            KnowledgeDependency(prerequisite=pre, dependent=dep, relation_type="required", weight=1, created_by=self.author)
            for pre, dep in zip(points, points[1:])])
        data = services.refresh_path(self.student.pk, points[-1].code)
        self.assertEqual([step["knowledge_code"] for step in data["steps"]], [point.code for point in points[:5]])

    def test_candidate_must_be_judgeable_and_unaccepted(self):
        self.problem.test_case_score = []
        self.problem.save()
        data = services.refresh_path(self.student.pk, "bfs")
        self.assertIsNone(data["steps"][0]["problem_id"])
        self.problem.test_case_score = [{"score": 100}]
        self.problem.save()
        self.submit()
        data = services.refresh_path(self.student.pk, "bfs")
        self.assertIsNone(data["steps"][0]["problem_id"])

    def test_teacher_is_membership_scoped_not_global_admin(self):
        klass = TeachingClass.objects.create(code="c1", name="Class", created_by=self.author, status="active")
        TeachingClassTeacher.objects.create(teaching_class=klass, teacher=self.teacher, granted_by=self.author)
        membership = TeachingClassStudent.objects.create(teaching_class=klass, student=self.student)
        self.client.force_login(self.teacher)
        path = f"admin/learning/student/{self.student.pk}/profile?class_id={klass.pk}"
        self.call("get", path)
        self.call("get", f"admin/learning/student/{self.other.pk}/profile?class_id={klass.pk}", expected=404)
        self.call("get", f"admin/learning/class/knowledge-stats?class_id={klass.pk}")
        self.call("get", f"admin/learning/class/knowledge-stats?class_id={klass.pk}&teacher_id={self.teacher.pk}", expected=400)
        membership.status = "left"
        membership.save()
        self.call("get", path, expected=404)
        self.client.force_login(self.author)
        self.call("get", f"admin/learning/class/knowledge-stats?class_id={klass.pk}", expected=404)
        self.call("get", f"admin/learning/class/knowledge-stats?class_id={klass.pk}", HTTP_X_AUDIT_REASON=quote("教学支持工单"))
        self.assertEqual(TeachingAccessEvent.objects.get().reason, "教学支持工单")

    def test_audit_reason_decodes_once_for_both_teacher_endpoints(self):
        klass = TeachingClass.objects.create(code="audit", name="Audit", created_by=self.author, status="active")
        TeachingClassStudent.objects.create(teaching_class=klass, student=self.student)
        self.client.force_login(self.author)
        reason = "教学支持：进度 100% + 工单%2F / 🙂"
        for path in (f"admin/learning/class/knowledge-stats?class_id={klass.pk}",
                     f"admin/learning/student/{self.student.pk}/profile?class_id={klass.pk}"):
            self.call("get", path, HTTP_X_AUDIT_REASON=quote(reason, safe=""))
        self.assertEqual(list(TeachingAccessEvent.objects.values_list("reason", flat=True)), [reason, reason])

    def test_audit_reason_rejects_invalid_wire_data_without_recording_access(self):
        klass = TeachingClass.objects.create(code="audit", name="Audit", created_by=self.author, status="active")
        self.client.force_login(self.author)
        path = f"admin/learning/class/knowledge-stats?class_id={klass.pk}"
        for value in ("中文", "%", "%2", "%ZZ", "%FF", "%ED%A0%80", "%00", "%0D%0A", "%C2%85", "a" * 1001,
                      "%20" * 1366):
            with self.subTest(value=value[:30]):
                self.call("get", path, expected=400, HTTP_X_AUDIT_REASON=value)
        for value in ("", "%20%20"):
            self.call("get", path, expected=404, HTTP_X_AUDIT_REASON=value)
        self.assertFalse(TeachingAccessEvent.objects.exists())

    def test_stats_excludes_left_disabled_and_other_class(self):
        klass = TeachingClass.objects.create(code="c1", name="Class", created_by=self.author, status="active")
        TeachingClassTeacher.objects.create(teaching_class=klass, teacher=self.teacher, granted_by=self.author)
        TeachingClassStudent.objects.create(teaching_class=klass, student=self.student)
        TeachingClassStudent.objects.create(teaching_class=klass, student=self.other, status="left")
        for user in (self.student, self.other):
            StudentKnowledgeState.objects.create(user=user, knowledge_point=self.point, rating=900, mastery_level="weak")
        data = services.class_stats(self.teacher, klass.pk)
        self.assertEqual(data["student_count"], 1)
        self.assertEqual(data["knowledge_stats"][0]["student_count"], 1)
        self.assertEqual(data["knowledge_stats"][0]["weak_count"], 1)

    def test_rating_idempotent_decimal_and_rejudge_removes_stale_credit(self):
        submission = self.submit()
        event = LearningSubmissionEvent.objects.get(submission=submission)
        ratings.process_event(event.pk)
        state = StudentKnowledgeState.objects.get(user=self.student)
        # Low difficulty is 1000; AC at initial 1200 has smaller than 16-point gain.
        self.assertEqual(state.rating, Decimal("1207.6881"))
        self.assertEqual(state.attempt_count, 1)
        ratings.process_event(event.pk)
        self.assertEqual(RatingHistory.objects.count(), 1)
        submission.result = -1
        with patch("learning.ratings.dispatch_event"):
            submission.save(update_fields=["result"])
        ratings.process_event(event.pk)
        state.refresh_from_db()
        self.assertEqual((state.rating, state.attempt_count, state.accepted_count), (Decimal("1175.6881"), 1, 0))
        event.refresh_from_db()
        self.assertEqual(event.revision, 2)
        self.assertNotIn("PRIVATE", json.dumps(event.payload))
        self.assertEqual(RatingHistory.objects.count(), 1)

    def test_rejudge_reopens_latest_completed_path_with_consistent_snapshot(self):
        path_data = services.refresh_path(self.student.pk, "bfs")
        path = LearningPath.objects.get(pk=path_data["path_id"])
        submission = self.submit()
        event = LearningSubmissionEvent.objects.get(submission=submission)
        ratings.process_event(event.pk)
        path.refresh_from_db()
        self.assertEqual(path.status, "completed")
        # A failed capture must not mix live verdicts with the old rating snapshot.
        Submission.objects.filter(pk=submission.pk).update(result=-1)
        ratings.replay_user(self.student.pk)
        path.refresh_from_db()
        self.assertEqual(path.status, "completed")
        self.assertEqual(StudentKnowledgeState.objects.get().accepted_count, 1)
        submission.refresh_from_db()
        with patch("learning.ratings.dispatch_event"):
            ratings.capture_submission(submission)
        ratings.process_event(event.pk)
        path.refresh_from_db()
        self.assertEqual(path.status, "active")
        self.assertEqual(path.steps.get().status, "pending")
        self.assertEqual(services.current_path(self.student.pk)["path_id"], str(path.pk))

    def test_rejudge_does_not_reactivate_older_expired_or_inactive_knowledge_path(self):
        from datetime import timedelta
        from django.utils import timezone
        path_data = services.refresh_path(self.student.pk, "bfs")
        path = LearningPath.objects.get(pk=path_data["path_id"])
        submission = self.submit()
        event = LearningSubmissionEvent.objects.get(submission=submission)
        ratings.process_event(event.pk)
        path.expires_time = timezone.now()-timedelta(seconds=1)
        path.save(update_fields=["expires_time"])
        submission.result = -1
        with patch("learning.ratings.dispatch_event"):
            submission.save(update_fields=["result"])
        ratings.process_event(event.pk)
        self.assertFalse(LearningPath.objects.filter(status="active").exists())
        path.status, path.expires_time = "completed", timezone.now()+timedelta(days=1)
        path.save(update_fields=["status", "expires_time"])
        self.point.status = "deprecated"
        self.point.save(update_fields=["status"])
        ratings.replay_user(self.student.pk)
        self.assertFalse(LearningPath.objects.filter(status="active").exists())
        self.point.status = "active"
        self.point.save(update_fields=["status"])
        newer = services.refresh_path(self.student.pk, "bfs")
        ratings.replay_user(self.student.pk)
        self.assertEqual(list(LearningPath.objects.filter(status="active").values_list("pk", flat=True)),
                         [LearningPath.objects.get(pk=newer["path_id"]).pk])

    def test_compile_system_and_pending_do_not_grade(self):
        pending = self.submit(6)
        self.assertFalse(LearningSubmissionEvent.objects.filter(submission=pending).exists())
        self.submit(5)
        compile_submission = self.submit(-2)
        ratings.process_event(LearningSubmissionEvent.objects.get(submission=compile_submission).pk)
        self.assertFalse(StudentKnowledgeState.objects.exists())
        ac = self.submit(0)
        event = LearningSubmissionEvent.objects.get(submission=ac)
        ratings.process_event(event.pk)
        ac.result = 5
        with patch("learning.ratings.dispatch_event"):
            ac.save(update_fields=["result"])
        ratings.process_event(event.pk)
        self.assertFalse(StudentKnowledgeState.objects.exists())
        self.assertFalse(RatingHistory.objects.exists())

    def test_multiple_mapping_normalization_and_repeat_decay(self):
        ProblemKnowledge.objects.create(problem=self.problem, knowledge_point=self.pre, role="secondary", weight=".5", reviewed_by=self.author)
        self.submit(-1)
        second = self.submit(-1)
        ratings.process_event(LearningSubmissionEvent.objects.get(submission=second).pk)
        states = {row.knowledge_point_id: row for row in StudentKnowledgeState.objects.all()}
        self.assertEqual(states[self.point.pk].attempt_count, 2)
        self.assertLess(states[self.point.pk].rating, states[self.pre.pk].rating)
        rows = list(RatingHistory.objects.filter(knowledge_point=self.point).order_by("submission__create_time"))
        self.assertLess(abs(rows[1].delta), abs(rows[0].delta))
        self.assertEqual(ProblemKnowledgeRating.objects.get(knowledge_point=self.point).accepted_count, 0)

    def test_batched_replay_preserves_other_users_and_clears_removed_pair_counts(self):
        ProblemKnowledge.objects.create(problem=self.problem, knowledge_point=self.pre, role="secondary",
                                        weight=".5", reviewed_by=self.author)
        first = self.submit(0)
        with patch("learning.ratings.dispatch_event"):
            second = Submission.objects.create(user_id=self.other.pk, username=self.other.username, problem=self.problem,
                                               code="", language="Python3", result=0)
        for submission in (first, second):
            ratings.process_event(LearningSubmissionEvent.objects.get(submission=submission).pk)
        self.assertEqual(list(ProblemKnowledgeRating.objects.values_list("attempt_count", "accepted_count")), [(2, 2), (2, 2)])
        for remaining, submission in [(1, first), (0, second)]:
            with patch("learning.ratings.dispatch_event"):
                submission.result = 5
                submission.save(update_fields=["result"])
            ratings.process_event(LearningSubmissionEvent.objects.get(submission=submission).pk)
            self.assertEqual(list(ProblemKnowledgeRating.objects.values_list("attempt_count", "accepted_count")),
                             [(remaining, remaining), (remaining, remaining)])
            self.assertEqual(StudentKnowledgeState.objects.count(), remaining * 2)

    def test_stored_mapping_snapshot_survives_mapping_changes(self):
        submission = self.submit(0)
        event = LearningSubmissionEvent.objects.get(submission=submission)
        ProblemKnowledge.objects.all().delete()
        ratings.process_event(event.pk)
        self.assertEqual(StudentKnowledgeState.objects.get().knowledge_point, self.point)

    def test_oi_partial_score_and_invalid_numeric(self):
        self.assertEqual(ratings.score_for(8, "OI", 25, 100), Decimal(".25"))
        self.assertEqual(ratings.score_for(8, "OI", 200, 100), Decimal("1"))
        self.assertIsNone(ratings.score_for(8, "OI", "NaN", 100))
        self.assertIsNone(ratings.score_for(8, "OI", None, 100))

    def test_queue_failure_keeps_recoverable_outbox(self):
        submission = self.submit()
        event = LearningSubmissionEvent.objects.get(submission=submission)
        with patch("learning.tasks.process_learning_event.send", side_effect=RuntimeError("private-url-token")):
            with self.assertLogs("learning.ratings", level="WARNING") as output:
                ratings.dispatch_event(event.pk)
        self.assertNotIn("private-url-token", str(output.output))
        event.refresh_from_db()
        self.assertEqual(event.error_code, "LEARNING_QUEUE_UNAVAILABLE")
        ratings.process_event(event.pk)
        event.refresh_from_db()
        self.assertEqual(event.status, "processed")


@override_settings(LEARNING_REFRESH_INTERVAL=0)
class LearningConcurrencyTests(LearningFixture, TransactionTestCase):
    def parallel(self, function):
        if connection.vendor != "postgresql":
            self.skipTest("real PostgreSQL locks required")
        barrier = threading.Barrier(2)

        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return function()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(lambda _: run(), range(2)))

    def test_same_refresh_key_in_two_connections_returns_one_path(self):
        results = self.parallel(lambda: services.refresh_path(self.student.pk, "bfs", "concurrent"))
        self.assertEqual(results[0], results[1])
        self.assertEqual(LearningPath.objects.count(), 1)
        self.assertEqual(LearningRefreshRequest.objects.count(), 1)

    def test_duplicate_worker_delivery_counts_submission_once(self):
        submission = self.submit()
        event = LearningSubmissionEvent.objects.get(submission=submission)
        self.parallel(lambda: ratings.process_event(event.pk))
        self.assertEqual(RatingHistory.objects.count(), 1)
        self.assertEqual(StudentKnowledgeState.objects.get().attempt_count, 1)


class LearningRecoveryTests(LearningFixture, TestCase):
    def test_capture_failure_rolls_back_verdict_and_backfill_repairs_legacy_rows(self):
        from django.core.management import call_command
        from .signals import LearningCaptureError
        submission = self.submit(6)
        with patch("learning.ratings.capture_submission", side_effect=RuntimeError("sensitive-detail")):
            with self.assertLogs("learning.signals", level="ERROR") as captured:
                with self.assertRaises(LearningCaptureError), transaction.atomic():
                    submission.result = 0
                    submission.save(update_fields=["result"])
        submission.refresh_from_db()
        self.assertEqual(submission.result, 6)
        self.assertNotIn("sensitive-detail", str(captured.output))
        self.assertFalse(LearningSubmissionEvent.objects.filter(submission=submission).exists())
        # Simulate an already-existing pre-fix row / bulk SQL write without a signal.
        Submission.objects.filter(pk=submission.pk).update(result=0)
        with patch("learning.ratings.dispatch_event"):
            call_command("recover_learning", backfill=True, sync=True, verbosity=0)
        self.assertEqual(StudentKnowledgeState.objects.get().attempt_count, 1)

    def test_async_redelivery_skips_recent_events_and_does_not_resend_each_pass(self):
        from datetime import timedelta
        from django.core.management import call_command
        from django.utils import timezone
        event = LearningSubmissionEvent.objects.get(submission=self.submit())
        with patch("learning.management.commands.recover_learning.dispatch_event") as dispatch:
            call_command("recover_learning", verbosity=0)
            dispatch.assert_not_called()
            LearningSubmissionEvent.objects.filter(pk=event.pk).update(updated_time=timezone.now() - timedelta(minutes=10))
            call_command("recover_learning", verbosity=0)
            call_command("recover_learning", verbosity=0)
        dispatch.assert_called_once_with(event.pk)

    def test_backfill_repairs_existing_stale_rejudge_and_partial_score(self):
        from django.core.management import call_command
        submission = self.submit()
        event = LearningSubmissionEvent.objects.get(submission=submission)
        ratings.process_event(event.pk)
        for result, score in ((-1, 0), (5, 0), (8, 25), (8, 75)):
            self.problem.rule_type, self.problem.total_score = "OI", 100
            self.problem.save(update_fields=["rule_type", "total_score"])
            submission.result, submission.statistic_info = result, {"score": score}
            # Pre-fix/direct SQL rows remain recoverable, although normal save now fails atomically.
            Submission.objects.filter(pk=submission.pk).update(result=result, statistic_info={"score": score})
            with patch("learning.ratings.dispatch_event"):
                call_command("recover_learning", backfill=True, sync=True, limit=1, verbosity=0)
            event.refresh_from_db()
            self.assertEqual(event.payload["result"], result)
            self.assertEqual(event.processed_revision, event.revision)
            if result == 5:
                self.assertFalse(RatingHistory.objects.exists())
            else:
                self.assertEqual(RatingHistory.objects.get().actual_score, Decimal(score)/100)
        self.assertEqual(event.payload["previous_results"][-1]["source"]["score"], 25)
        self.assertIsNotNone(event.payload["previous_results"][-1]["captured_time"])

    def test_backfill_limit_advances_past_unchanged_rows_and_bootstraps_old_sources(self):
        from django.core.management import call_command
        # Legacy Submission.user_id is not a FK; removed users must not consume
        # every recovery batch ahead of valid later submissions.
        Submission.objects.create(user_id=999999999, username="deleted-student", problem=self.problem,
                                  code="", language="Python3", result=0)
        old, newer = self.submit(), self.submit()
        old_event = LearningSubmissionEvent.objects.get(submission=old)
        ratings.process_event(old_event.pk)
        # Emulate an event written before source reconciliation was introduced.
        del old_event.payload["source"]
        old_event.save(update_fields=["payload"])
        Submission.objects.filter(pk=newer.pk).update(result=6)
        with patch("learning.ratings.dispatch_event"):
            call_command("recover_learning", backfill=True, sync=True, limit=1, verbosity=0)
            old_event.refresh_from_db()
            self.assertIn("source", old_event.payload)
            self.assertEqual(old_event.revision, 1)
            call_command("recover_learning", backfill=True, sync=True, limit=1, verbosity=0)
        newer_event = LearningSubmissionEvent.objects.get(submission=newer)
        self.assertEqual(newer_event.payload["result"], 6)
        self.assertEqual(newer_event.status, "processed")
        self.assertEqual(StudentKnowledgeState.objects.get().attempt_count, 1)

    def test_failed_worker_does_not_overwrite_success_or_new_revision(self):
        from .tasks import process_learning_event
        submission = self.submit()
        event = LearningSubmissionEvent.objects.get(submission=submission)

        def succeeded_elsewhere(_):
            ratings.process_event(event.pk)
            raise RuntimeError("late worker failure")

        with patch("learning.tasks.process_event", side_effect=succeeded_elsewhere):
            with self.assertRaisesRegex(RuntimeError, "LEARNING_PROCESSING_FAILED"):
                process_learning_event.fn(event.pk)
        event.refresh_from_db()
        self.assertEqual(event.status, "processed")

        def revised_elsewhere(_):
            submission.result = -1
            with patch("learning.ratings.dispatch_event"):
                submission.save(update_fields=["result"])
            raise RuntimeError("old revision failed")

        with patch("learning.tasks.process_event", side_effect=revised_elsewhere):
            with self.assertRaisesRegex(RuntimeError, "LEARNING_PROCESSING_FAILED"):
                process_learning_event.fn(event.pk)
        event.refresh_from_db()
        self.assertEqual(event.status, "pending")
        self.assertEqual(event.error_code, "")

    def test_confidence_ages_without_changing_rating(self):
        from datetime import timedelta
        from django.utils import timezone
        state = StudentKnowledgeState.objects.create(user=self.student, knowledge_point=self.point,
                                                     rating=1300, confidence=".800", last_submission_time=timezone.now()-timedelta(days=7))
        self.assertEqual(services.effective_confidence(state), Decimal(".400"))
        self.assertEqual(services.student_profile(self.student.pk)["knowledge_states"][0]["rating"], 1300)

    def test_roster_requires_admin_and_is_atomic_on_invalid_members(self):
        import tempfile
        from pathlib import Path
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"roster.json"
            data = {"code": "test-class", "name": "Test", "term": "2026", "teachers": [{"username": self.teacher.username}],
                    "students": [{"username": self.student.username, "student_number": "001"}]}
            path.write_text(json.dumps(data))
            with self.assertRaises(CommandError):
                call_command("sync_teaching_class", str(path), actor=self.student.username, reason="test")
            call_command("sync_teaching_class", str(path), actor=self.author.username, reason="test")
            self.assertEqual(TeachingClassStudent.objects.count(), 1)
            self.assertEqual(TeachingClassTeacher.objects.count(), 1)
            data["students"].append({"username": self.other.username, "student_number": "001"})
            path.write_text(json.dumps(data))
            with self.assertRaises(CommandError):
                call_command("sync_teaching_class", str(path), actor=self.author.username, reason="conflict")
            self.assertEqual(TeachingClassStudent.objects.count(), 1)
            self.assertEqual(TeachingAccessEvent.objects.count(), 1)

    def test_class_owner_may_merge_only_their_active_class_members(self):
        import tempfile
        from pathlib import Path
        from django.core.management import call_command
        from django.core.management.base import CommandError
        klass = TeachingClass.objects.create(code="owned", name="Owned", course_name="Algorithms", term="2026", created_by=self.author)
        TeachingClassTeacher.objects.create(teaching_class=klass, teacher=self.teacher, role="owner", granted_by=self.author)
        other_class = TeachingClass.objects.create(code="other", name="Other", term="2026", created_by=self.author)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"roster.json"
            data = {"code": klass.code, "name": klass.name, "term": klass.term,
                    "teachers": [{"username": self.other.username}], "students": [{"username": self.student.username}]}
            path.write_text(json.dumps(data))
            call_command("sync_teaching_class", str(path), actor=self.teacher.username, reason="Owner update")
            self.assertEqual(klass.teachers.count(), 2)
            self.assertEqual(klass.students.count(), 1)
            self.assertEqual(TeachingAccessEvent.objects.get().actor, self.teacher)
            for actor, payload in (
                (self.other, data),
                (self.teacher, {**data, "name": "Rename forbidden"}),
                (self.teacher, {**data, "status": "archived"}),
                (self.teacher, {**data, "code": other_class.code, "name": other_class.name}),
                (self.teacher, {**data, "code": "new-class"}),
            ):
                path.write_text(json.dumps(payload))
                with self.assertRaises(CommandError):
                    call_command("sync_teaching_class", str(path), actor=actor.username, reason="Denied")
            klass.refresh_from_db()
            self.assertEqual((klass.name, klass.course_name, klass.status), ("Owned", "Algorithms", "active"))
            self.assertEqual(TeachingClass.objects.count(), 2)
            self.assertEqual(TeachingAccessEvent.objects.count(), 1)

    def test_success_responses_validate_working_openapi(self):
        from pathlib import Path
        import yaml
        from openapi_schema_validator import OAS30Validator
        spec = yaml.safe_load((Path(__file__).resolve().parents[2]/"docs/openapi/learning-api-v1.yaml").read_text())

        def check(body, name):
            schema = {"$ref": "#/components/schemas/"+name, "components": spec["components"]}
            OAS30Validator(schema).validate(body)
        check(self.call("get", "learning/profile"), "StudentProfileEnvelope")
        check(self.call("get", "learning/weakness"), "WeaknessEnvelope")
        check(self.call("post", "recommendation/refresh", {}), "LearningPathEnvelope")
        submission = self.submit()
        ratings.process_event(LearningSubmissionEvent.objects.get(submission=submission).pk)
        check(self.call("get", "learning/profile"), "StudentProfileEnvelope")
        check(self.call("get", "learning/weakness"), "WeaknessEnvelope")

    def test_legacy_delete_preserves_new_audited_references(self):
        from problem.models import Problem
        self.client.force_login(self.author)
        response = self.client.delete(f"/api/admin/problem?id={self.problem.pk}")
        self.assertEqual(response.json()["error"], "resource-in-use")
        self.assertTrue(Problem.objects.filter(pk=self.problem.pk).exists())
        StudentKnowledgeState.objects.create(user=self.student, knowledge_point=self.point)
        response = self.client.delete(f"/api/admin/user?id={self.student.pk}")
        self.assertEqual(response.json()["error"], "resource-in-use")
        self.assertTrue(User.objects.filter(pk=self.student.pk).exists())

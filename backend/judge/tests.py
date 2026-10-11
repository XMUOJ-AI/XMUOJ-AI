import copy
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.db import close_old_connections, OperationalError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TransactionTestCase
from django.utils import timezone

from account.models import UserProfile
from contest.models import ACMContestRank, Contest
from knowledge.models import ProblemKnowledge
from knowledge.tests import make_point, make_problem, make_user
from learning.models import LearningSubmissionEvent, RatingHistory, StudentKnowledgeState
from learning.ratings import process_event
from submission.models import JudgeStatus, Submission

from .dispatcher import JudgeDispatcher


@contextmanager
def available_server():
    yield SimpleNamespace(service_url="http://judge.invalid")


def judge_response(result=0):
    return {"err": None, "data": [{"result": result, "cpu_time": 1, "memory": 1024, "test_case": "1"}]}


class RejudgeIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.admin = make_user("judge-admin")
        self.student = make_user("judge-student", admin_type="Regular User", permission="None")
        for user in (self.admin, self.student):
            UserProfile.objects.create(user=user)
        self.problem = make_problem(self.admin, "JUDGE-1")
        self.problem.test_case_score = [{"input_name": "1.in", "output_name": "1.out", "score": 100}]
        self.problem.save()
        point = make_point("judge-point", self.admin)
        ProblemKnowledge.objects.create(problem=self.problem, knowledge_point=point, role="primary",
                                        weight="1", reviewed_by=self.admin)
        mocked = patch("learning.ratings.dispatch_event")
        mocked.start()
        self.addCleanup(mocked.stop)
        waiting = patch("judge.dispatcher.process_pending_task")
        waiting.start()
        self.addCleanup(waiting.stop)

    def submission(self, problem=None):
        problem = problem or self.problem
        return Submission.objects.create(problem=problem, contest=problem.contest, user_id=self.student.pk,
                                         username=self.student.username, language="Python3", code="print(3)")

    def judge(self, submission, response=None):
        response = judge_response() if response is None else response
        with patch("judge.dispatcher.ChooseJudgeServer", side_effect=available_server), \
                patch.object(JudgeDispatcher, "_request", return_value=copy.deepcopy(response)):
            JudgeDispatcher(submission.pk, submission.problem_id).judge()
        submission.refresh_from_db()
        event = LearningSubmissionEvent.objects.filter(submission=submission).first()
        if event:
            process_event(event.pk)
        return submission

    def rejudge(self, submission, user=None):
        self.client.force_login(user or self.admin)
        with patch("submission.views.admin.judge_task.send") as send:
            response = self.client.post("/api/admin/submission/rejudge", json.dumps({"id": submission.pk}),
                                        content_type="application/json")
        return response.json(), send

    def test_public_ac_wa_ac_replays_learning_once_and_repairs_legacy_counts(self):
        submission = self.judge(self.submission())
        initial_rating = StudentKnowledgeState.objects.get(user=self.student).rating
        for result, accepted in ((JudgeStatus.WRONG_ANSWER, 0), (JudgeStatus.ACCEPTED, 1)):
            response, send = self.rejudge(submission)
            self.assertIsNone(response["error"])
            send.assert_called_once()
            self.judge(submission, judge_response(result))
            self.problem.refresh_from_db()
            profile = UserProfile.objects.get(user=self.student)
            state = StudentKnowledgeState.objects.get(user=self.student)
            self.assertEqual(self.problem.statistic_info, {str(result): 1})
            self.assertEqual((self.problem.submission_number, self.problem.accepted_number), (1, accepted))
            self.assertEqual((profile.submission_number, profile.accepted_number), (1, accepted))
            self.assertEqual((state.attempt_count, state.accepted_count), (1, accepted))
            self.assertEqual(RatingHistory.objects.filter(submission=submission).count(), 1)
        self.assertEqual(StudentKnowledgeState.objects.get(user=self.student).rating, initial_rating)

    def test_oi_request_keeps_previous_score_until_worker_and_updates_total_score(self):
        self.problem.rule_type, self.problem.total_score = "OI", 100
        self.problem.save()
        submission = self.judge(self.submission())
        event = LearningSubmissionEvent.objects.get(submission=submission)
        previous_revision = event.revision
        self.rejudge(submission)
        submission.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(submission.statistic_info["score"], 100)
        self.assertEqual(event.revision, previous_revision)
        self.assertEqual(event.payload["actual"], "1")
        self.judge(submission, judge_response(JudgeStatus.WRONG_ANSWER))
        profile = UserProfile.objects.get(user=self.student)
        self.assertEqual((profile.total_score, profile.accepted_number), (0, 0))
        self.rejudge(submission)
        self.judge(submission)
        profile.refresh_from_db()
        self.assertEqual((profile.total_score, profile.accepted_number, profile.submission_number), (100, 1, 1))

    def test_rejudge_preserves_credit_from_another_accepted_submission(self):
        first = self.judge(self.submission())
        self.judge(self.submission())
        self.rejudge(first)
        self.judge(first, judge_response(JudgeStatus.WRONG_ANSWER))
        profile = UserProfile.objects.get(user=self.student)
        self.problem.refresh_from_db()
        self.assertEqual((self.problem.accepted_number, self.problem.submission_number), (1, 2))
        self.assertEqual((profile.accepted_number, profile.submission_number), (1, 2))
        self.assertEqual(profile.acm_problems_status["problems"][str(self.problem.pk)]["status"], 0)

    def test_compile_error_rejudge_and_system_error_withdraw_old_credit(self):
        submission = self.judge(self.submission(), {"err": "CompileError", "data": "compiler diagnostics"})
        self.assertEqual(submission.result, JudgeStatus.COMPILE_ERROR)
        self.rejudge(submission)
        self.judge(submission)
        self.problem.refresh_from_db()
        self.assertEqual(self.problem.submission_number, 1)
        self.rejudge(submission)
        with patch("judge.dispatcher.ChooseJudgeServer", side_effect=available_server), \
                patch.object(JudgeDispatcher, "_request", return_value=None):
            JudgeDispatcher(submission.pk, self.problem.pk).judge()
        process_event(LearningSubmissionEvent.objects.get(submission=submission).pk)
        self.problem.refresh_from_db()
        self.assertEqual(self.problem.accepted_number, 0)
        self.assertFalse(StudentKnowledgeState.objects.filter(user=self.student).exists())

    def test_duplicate_and_concurrent_delivery_do_not_rejudge_or_count_twice(self):
        submission = self.submission()
        barrier = threading.Barrier(2)

        def call_remote(*args, **kwargs):
            time.sleep(.05)
            return judge_response()

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                JudgeDispatcher(submission.pk, self.problem.pk).judge()
            finally:
                close_old_connections()

        with patch("judge.dispatcher.ChooseJudgeServer", side_effect=available_server), \
                patch.object(JudgeDispatcher, "_request", side_effect=call_remote) as request:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker) for _ in range(2)]
                for future in futures:
                    future.result()
            JudgeDispatcher(submission.pk, self.problem.pk).judge()
        self.assertEqual(request.call_count, 1)
        self.problem.refresh_from_db()
        self.assertEqual((self.problem.submission_number, self.problem.accepted_number), (1, 1))
        event = LearningSubmissionEvent.objects.get(submission=submission)
        process_event(event.pk)
        self.assertEqual(RatingHistory.objects.filter(submission=submission).count(), 1)
        self.assertEqual(event.revision, 1)

    def test_contest_is_excluded_from_learning_and_permissions_stay_scoped(self):
        contest = Contest.objects.create(title="Contest", description="", real_time_rank=True, rule_type="ACM",
                                         start_time=timezone.now() - timedelta(hours=1),
                                         end_time=timezone.now() + timedelta(hours=1), created_by=self.admin)
        self.problem.contest = contest
        self.problem.save()
        submission = self.judge(self.submission())
        rank = ACMContestRank.objects.get(contest=contest, user=self.student)
        self.assertEqual((rank.accepted_number, rank.submission_number), (1, 1))
        self.judge(submission)
        rank.refresh_from_db()
        self.assertEqual((rank.accepted_number, rank.submission_number), (1, 1))
        self.assertFalse(LearningSubmissionEvent.objects.exists())
        self.assertFalse(RatingHistory.objects.exists())
        response, send = self.rejudge(submission, self.student)
        self.assertIsNotNone(response["error"])
        send.assert_not_called()

    def test_rejudge_get_is_read_only_and_session_post_requires_csrf(self):
        submission = self.judge(self.submission())
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        endpoint = "/api/admin/submission/rejudge"
        with patch("submission.views.admin.judge_task.send") as send:
            self.assertEqual(client.get(endpoint, {"id": submission.pk}).status_code, 405)
            self.assertEqual(client.post(endpoint, json.dumps({"id": submission.pk}),
                                         content_type="application/json").status_code, 403)
            send.assert_not_called()
            token = "c" * 32
            client.cookies["csrftoken"] = token
            response = client.post(endpoint, json.dumps({"id": submission.pk}), content_type="application/json",
                                   HTTP_X_CSRFTOKEN=token)
            self.assertIsNone(response.json()["error"])
            send.assert_called_once()

    def test_concurrent_distinct_submissions_have_two_attempts_and_one_solved_problem(self):
        submissions = [self.submission(), self.submission()]
        barrier = threading.Barrier(2)

        def worker(submission):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                JudgeDispatcher(submission.pk, self.problem.pk).judge()
            finally:
                close_old_connections()

        with patch("judge.dispatcher.ChooseJudgeServer", side_effect=available_server), \
                patch.object(JudgeDispatcher, "_request", side_effect=lambda *args, **kwargs: judge_response()):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker, submission) for submission in submissions]
                for future in futures:
                    future.result()
        self.problem.refresh_from_db()
        profile = UserProfile.objects.get(user=self.student)
        self.assertEqual(self.problem.statistic_info, {"0": 2})
        self.assertEqual((self.problem.submission_number, self.problem.accepted_number), (2, 2))
        self.assertEqual((profile.submission_number, profile.accepted_number), (2, 1))
        for event in LearningSubmissionEvent.objects.all():
            process_event(event.pk)
        state = StudentKnowledgeState.objects.get(user=self.student)
        self.assertEqual((state.attempt_count, state.accepted_count), (2, 2))

    def test_autocommit_save_rolls_back_without_outer_transaction(self):
        from learning.signals import LearningCaptureError
        submission = self.submission()
        with patch("learning.ratings.capture_submission", side_effect=OperationalError("unavailable")):
            with self.assertLogs("learning.signals", level="ERROR"), self.assertRaises(LearningCaptureError) as failure:
                submission.result = 0
                submission.save(update_fields=["result"])
        self.assertTrue(failure.exception.retryable)
        submission.refresh_from_db()
        self.assertEqual(submission.result, JudgeStatus.PENDING)
        self.assertFalse(LearningSubmissionEvent.objects.filter(submission=submission).exists())

    def test_judge_capture_failure_rolls_back_then_retry_commits_once(self):
        from learning import ratings
        from learning.signals import LearningCaptureError
        submission = self.submission()
        capture = ratings.capture_submission

        def fail_terminal(instance):
            if instance.result == JudgeStatus.ACCEPTED:
                raise OperationalError("temporary lock failure")
            return capture(instance)

        with patch("learning.ratings.capture_submission", side_effect=fail_terminal):
            with self.assertLogs("learning.signals", level="ERROR"), self.assertRaises(LearningCaptureError):
                self.judge(submission)
        submission.refresh_from_db()
        self.problem.refresh_from_db()
        self.assertEqual(submission.result, JudgeStatus.JUDGING)
        self.assertEqual(self.problem.submission_number, 0)
        self.assertFalse(LearningSubmissionEvent.objects.filter(submission=submission).exists())
        self.judge(submission)
        self.judge(submission)
        self.assertEqual(LearningSubmissionEvent.objects.filter(submission=submission).count(), 1)
        self.assertEqual(RatingHistory.objects.filter(submission=submission).count(), 1)
        self.assertEqual(StudentKnowledgeState.objects.get(user=self.student).attempt_count, 1)

    def test_capture_retries_are_bounded_and_exclude_programming_errors(self):
        from judge.tasks import judge_task, retry_learning_capture
        from learning.signals import LearningCaptureError
        self.assertIs(judge_task.options["retry_when"], retry_learning_capture)
        self.assertEqual(judge_task.options["max_retries"], 3)
        for attempt in range(5):
            self.assertEqual(retry_learning_capture(attempt, LearningCaptureError(retryable=True)), attempt < 3)
            self.assertFalse(retry_learning_capture(attempt, LearningCaptureError(retryable=False)))
            self.assertFalse(retry_learning_capture(attempt, RuntimeError("programming error")))

    def test_explicit_operator_recovery_requeues_only_judging(self):
        submission = self.submission()
        Submission.objects.filter(pk=submission.pk).update(result=JudgeStatus.JUDGING)
        with patch("judge.management.commands.recover_judge.judge_task.send") as send:
            call_command("recover_judge", submission.pk, stdout=io.StringIO())
        send.assert_called_once_with(submission.pk, submission.problem_id)
        Submission.objects.filter(pk=submission.pk).update(result=JudgeStatus.ACCEPTED)
        with self.assertRaises(CommandError), patch("judge.management.commands.recover_judge.judge_task.send") as send:
            call_command("recover_judge", submission.pk, stdout=io.StringIO())
        send.assert_not_called()

    def test_rejudge_capture_failure_preserves_old_verdict_revision_and_dispatch(self):
        from learning import ratings
        from learning.signals import LearningCaptureError
        submission = self.judge(self.submission())
        event = LearningSubmissionEvent.objects.get(submission=submission)
        previous_revision = event.revision
        capture = ratings.capture_submission

        def fail_after_capture(instance):
            capture(instance)
            raise OperationalError("failure after event update")

        with patch("learning.ratings.capture_submission", side_effect=fail_after_capture), \
                patch("learning.ratings.dispatch_event") as dispatch:
            with self.assertLogs("learning.signals", level="ERROR"), self.assertRaises(LearningCaptureError):
                submission.result = JudgeStatus.WRONG_ANSWER
                submission.save(update_fields=["result"])
        submission.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(submission.result, JudgeStatus.ACCEPTED)
        self.assertEqual((event.revision, event.processed_revision), (previous_revision, previous_revision))
        self.assertEqual(StudentKnowledgeState.objects.get(user=self.student).accepted_count, 1)
        dispatch.assert_not_called()

    def test_new_pending_submission_does_not_acquire_learning_graph_lock(self):
        with patch("learning.ratings.knowledge_write") as graph_lock:
            self.submission()
        graph_lock.assert_not_called()

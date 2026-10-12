import copy
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone

from account.models import User, UserProfile
from judge.dispatcher import JudgeDispatcher
from judge.tests import available_server, judge_response
from knowledge.tests import make_problem, make_user
from submission.models import JudgeStatus, Submission
from utils.cache import cache
from utils.constants import CacheKey
from .models import ACMContestRank, Contest, ContestParticipation, OIContestRank
from .scoring import rebuild_contest_scores


class ContestScoringTests(TransactionTestCase):
    def setUp(self):
        self.admin = make_user("score-owner")
        self.student = self.user("score-student")
        self.contest = Contest.objects.create(
            title="Scores", description="", rule_type="ACM", real_time_rank=True,
            start_time=timezone.now() - timedelta(hours=2), end_time=timezone.now() - timedelta(hours=1), created_by=self.admin)
        self.problem = self.problem_for("SCORE-1")
        self.pending = patch("judge.dispatcher.process_pending_task")
        self.pending.start()
        self.addCleanup(self.pending.stop)

    def user(self, name):
        user = make_user(name, admin_type="Regular User", permission="None")
        UserProfile.objects.create(user=user)
        return user

    def problem_for(self, display_id):
        problem = make_problem(self.admin, display_id)
        problem.contest, problem.rule_type = self.contest, self.contest.rule_type
        problem.total_score = 100
        problem.test_case_score = [{"input_name": "1.in", "output_name": "1.out", "score": 100}]
        problem.save()
        return problem

    def submission(self, seconds, result=JudgeStatus.PENDING, user=None, problem=None, score=None):
        user, problem = user or self.student, problem or self.problem
        submission = Submission.objects.create(contest=self.contest, problem=problem, user_id=user.pk, username=user.username,
                                               code="print(1)", language="Python3", result=result,
                                               statistic_info={} if score is None else {"score": score})
        Submission.objects.filter(pk=submission.pk).update(create_time=self.contest.start_time + timedelta(seconds=seconds))
        submission.refresh_from_db()
        return submission

    def judge(self, submission, response):
        with patch("judge.dispatcher.ChooseJudgeServer", side_effect=available_server), \
                patch.object(JudgeDispatcher, "_request", return_value=copy.deepcopy(response)):
            JudgeDispatcher(submission.pk, submission.problem_id).judge()
        submission.refresh_from_db()

    def rejudge(self, submission, response):
        self.client.force_login(self.admin)
        with patch("judge.tasks.judge_task.send"):
            result = self.client.post("/api/admin/submission/rejudge", json.dumps({"id": submission.pk}), content_type="application/json")
        self.assertIsNone(result.json()["error"])
        self.judge(submission, response)

    def test_acm_after_end_rejudge_rebuilds_first_ac_and_prior_penalties(self):
        attempts = [self.submission(seconds) for seconds in (10, 20, 40, 50, 60)]
        responses = [{"err": "CompileError", "data": "error"}, judge_response(-1), judge_response(), judge_response(-1), judge_response()]
        for attempt, response in zip(attempts, responses):
            self.judge(attempt, response)
        rank = ACMContestRank.objects.get(contest=self.contest, user=self.student)
        self.assertEqual((rank.submission_number, rank.accepted_number, rank.total_time), (5, 1, 1240))
        self.rejudge(attempts[2], judge_response(-1))
        rank.refresh_from_db()
        self.assertEqual(rank.total_time, 3660)
        self.assertEqual(rank.submission_info[str(self.problem.pk)]["error_number"], 3)
        self.rejudge(attempts[1], judge_response())
        self.judge(attempts[1], judge_response())
        rank.refresh_from_db()
        self.problem.refresh_from_db()
        self.assertEqual((rank.submission_number, rank.accepted_number, rank.total_time), (5, 1, 20))
        self.assertEqual((self.problem.submission_number, self.problem.accepted_number), (5, 2))
        participation = ContestParticipation.calibrate_once(self.student, self.contest, force=True)
        self.assertEqual((participation.submission_number, participation.accepted_number), (5, 1))

    def test_first_ac_moves_to_another_user_and_system_error_withdraws_credit(self):
        other = self.user("score-other")
        first, second = self.submission(20), self.submission(30, user=other)
        self.judge(first, judge_response())
        self.judge(second, judge_response())
        key = str(self.problem.pk)
        rank = ACMContestRank.objects.get(user=self.student, contest=self.contest)
        rank.submission_info[key]["checked"] = True
        rank.save()
        rebuild_contest_scores(self.contest.pk, self.student.pk, self.problem.pk)
        rank.refresh_from_db()
        self.assertTrue(rank.submission_info[key]["checked"])
        self.rejudge(first, judge_response(-1))
        rank.refresh_from_db()
        other_rank = ACMContestRank.objects.get(user=other, contest=self.contest)
        self.assertFalse(rank.submission_info[key]["is_first_ac"])
        self.assertNotIn("checked", rank.submission_info[key])
        self.assertTrue(other_rank.submission_info[key]["is_first_ac"])
        self.rejudge(second, None)
        self.assertFalse(ACMContestRank.objects.filter(user=other, contest=self.contest).exists())
        self.problem.refresh_from_db()
        self.assertEqual((self.problem.submission_number, self.problem.accepted_number), (1, 0))
        self.assertEqual(ContestParticipation.objects.get(user=other, contest=self.contest).accepted_number, 0)

    def test_oi_uses_highest_valid_score_and_calibration_cannot_restore_revoked_score(self):
        self.contest.rule_type = self.problem.rule_type = "OI"
        self.contest.save(update_fields=["rule_type"])
        self.problem.save(update_fields=["rule_type"])
        first = self.submission(10)
        self.judge(first, judge_response())
        self.submission(20, result=JudgeStatus.PARTIALLY_ACCEPTED, score=30)
        self.submission(30, result=JudgeStatus.PARTIALLY_ACCEPTED, score=70)
        self.submission(40, result=JudgeStatus.PARTIALLY_ACCEPTED, score="999")
        self.submission(50, result=JudgeStatus.PARTIALLY_ACCEPTED, score=999)
        rebuild_contest_scores(self.contest.pk)
        self.assertEqual(OIContestRank.objects.get(user=self.student, contest=self.contest).total_score, 100)
        self.rejudge(first, judge_response(-1))
        participation = ContestParticipation.calibrate_once(self.student, self.contest, force=True)
        rank = OIContestRank.objects.get(user=self.student, contest=self.contest)
        self.assertEqual((rank.total_score, rank.submission_number, participation.total_score, participation.accepted_number), (70, 5, 70, 0))
        profile = UserProfile.objects.get(user=self.student)
        self.assertEqual(profile.oi_problems_status["contest_problems"][str(self.problem.pk)]["status"], JudgeStatus.PARTIALLY_ACCEPTED)
        self.client.force_login(self.student)
        # Resolve named routes to preserve the public API's existing URL conventions.
        from django.urls import reverse
        summary = self.client.get(reverse("user_contest_summary_api")).json()
        self.assertEqual(summary["data"]["results"][0]["total_score"], 70)
        detail = self.client.get(reverse("user_contest_detail_api"), {"contest_id": self.contest.pk}).json()
        self.assertEqual((detail["data"]["total_score"], detail["data"]["ac_count"]), (70, 0))
        self.assertFalse(detail["data"]["problem_items"][0]["is_ac"])

    def test_eligibility_excludes_invalid_users_outside_window_and_non_verdict_states(self):
        self.submission(0, result=JudgeStatus.WRONG_ANSWER)
        self.submission(3600, result=JudgeStatus.ACCEPTED)
        for seconds in (-1, 3601):
            self.submission(seconds, result=JudgeStatus.ACCEPTED)
        for result in (JudgeStatus.PENDING, JudgeStatus.JUDGING, JudgeStatus.SYSTEM_ERROR):
            self.submission(10, result=result)
        disabled = self.user("score-disabled")
        self.submission(10, result=JudgeStatus.ACCEPTED, user=disabled)
        User.objects.filter(pk=disabled.pk).update(is_disabled=True)
        deleted = self.user("score-deleted")
        self.submission(10, result=JudgeStatus.ACCEPTED, user=deleted)
        deleted.delete()
        self.submission(10, result=JudgeStatus.ACCEPTED, user=self.admin)
        foreign = make_problem(self.admin, "SCORE-FOREIGN")
        self.submission(10, result=JudgeStatus.ACCEPTED, problem=foreign)
        hidden = self.problem_for("SCORE-HIDDEN")
        self.submission(10, result=JudgeStatus.ACCEPTED, problem=hidden)
        hidden.visible = False
        hidden.save(update_fields=["visible"])
        self.assertEqual(rebuild_contest_scores(self.contest.pk), 2)
        rank = ACMContestRank.objects.get(contest=self.contest)
        self.assertEqual((rank.user_id, rank.submission_number, rank.accepted_number, rank.total_time), (self.student.pk, 2, 1, 4800))
        self.problem.refresh_from_db()
        self.assertEqual((self.problem.submission_number, self.problem.accepted_number), (2, 1))

    def test_oi_ac_fact_is_independent_of_missing_or_invalid_historical_score(self):
        from django.urls import reverse
        self.contest.rule_type = self.problem.rule_type = "OI"
        self.contest.save(update_fields=["rule_type"])
        self.problem.save(update_fields=["rule_type"])
        accepted = self.submission(10, result=JudgeStatus.ACCEPTED)
        self.submission(20, result=JudgeStatus.PARTIALLY_ACCEPTED, score=70)
        self.client.force_login(self.student)
        for stats in ({}, {"score": "100"}, {"score": 101}, {"score": True}, {"score": -1}):
            with self.subTest(stats=stats):
                Submission.objects.filter(pk=accepted.pk).update(statistic_info=stats)
                rebuild_contest_scores(self.contest.pk)
                rank = OIContestRank.objects.get(user=self.student, contest=self.contest)
                participation = ContestParticipation.objects.get(user=self.student, contest=self.contest)
                self.assertEqual((rank.total_score, participation.total_score, participation.accepted_number), (70, 70, 1))
                status = UserProfile.objects.get(user=self.student).oi_problems_status["contest_problems"][str(self.problem.pk)]
                self.assertEqual((status["status"], status["score"]), (JudgeStatus.ACCEPTED, 70))
                detail = self.client.get(reverse("user_contest_detail_api"), {"contest_id": self.contest.pk}).json()
                self.assertIsNone(detail["error"])
                self.assertEqual((detail["data"]["total_score"], detail["data"]["ac_count"]), (70, 1))
                self.assertTrue(detail["data"]["problem_items"][0]["is_ac"])
                self.assertEqual(detail["data"]["problem_items"][0]["best_score"], 70)

    def test_rebuild_and_rejudge_preserve_existing_participation_entry_history(self):
        attempt = self.submission(10)
        self.judge(attempt, judge_response())
        participation = ContestParticipation.objects.get(user=self.student, contest=self.contest)
        first_enter = self.contest.start_time - timedelta(minutes=2)
        last_enter = self.contest.start_time + timedelta(minutes=2)
        ContestParticipation.objects.filter(pk=participation.pk).update(
            first_enter_time=first_enter, last_enter_time=last_enter, enter_count=7)
        rebuild_contest_scores(self.contest.pk)
        participation.refresh_from_db()
        self.assertEqual((participation.first_enter_time, participation.last_enter_time, participation.enter_count),
                         (first_enter, last_enter, 7))
        self.assertEqual((participation.submission_number, participation.accepted_number), (1, 1))
        self.rejudge(attempt, judge_response(-1))
        participation.refresh_from_db()
        self.assertEqual((participation.first_enter_time, participation.last_enter_time, participation.enter_count),
                         (first_enter, last_enter, 7))
        self.assertEqual((participation.submission_number, participation.accepted_number), (1, 0))

    def test_explicit_rebuild_removes_deleted_submissions_and_disabled_users(self):
        other = self.user("score-remove")
        first, second = self.submission(10), self.submission(20, user=other)
        self.judge(first, judge_response())
        self.judge(second, judge_response())
        first.delete()
        User.objects.filter(pk=other.pk).update(is_disabled=True)
        call_command("rebuild_contest_scores", self.contest.pk, stdout=io.StringIO())
        self.assertFalse(ACMContestRank.objects.filter(contest=self.contest).exists())
        self.assertFalse(ContestParticipation.objects.filter(contest=self.contest, accepted_number__gt=0).exists())
        self.problem.refresh_from_db()
        self.assertEqual(self.problem.submission_number, 0)
        for user in (self.student, other):
            self.assertNotIn(str(self.problem.pk), UserProfile.objects.get(user=user).acm_problems_status["contest_problems"])

    def test_concurrent_distinct_submissions_are_rebuilt_once(self):
        second_problem = self.problem_for("SCORE-2")
        submissions = [self.submission(10), self.submission(20, problem=second_problem)]
        barrier = threading.Barrier(2)

        def remote(*args, **kwargs):
            barrier.wait(timeout=5)
            return judge_response()

        def worker(submission):
            close_old_connections()
            try:
                JudgeDispatcher(submission.pk, submission.problem_id).judge()
            finally:
                close_old_connections()

        with patch("judge.dispatcher.ChooseJudgeServer", side_effect=available_server), patch.object(JudgeDispatcher, "_request", side_effect=remote):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker, submission) for submission in submissions]
                for future in futures:
                    future.result(timeout=10)
        for submission in submissions:
            self.judge(submission, judge_response())
        rank = ACMContestRank.objects.get(contest=self.contest, user=self.student)
        self.assertEqual((rank.submission_number, rank.accepted_number, rank.total_time), (2, 2, 30))

    def test_rebuild_after_problem_deletion_clears_only_its_profile_entries(self):
        attempt = self.submission(10)
        self.judge(attempt, judge_response())
        unrelated = make_problem(self.admin, "SCORE-UNRELATED")
        profile = UserProfile.objects.get(user=self.student)
        profile.acm_problems_status["contest_problems"][str(unrelated.pk)] = {"status": JudgeStatus.ACCEPTED, "_id": unrelated._id}
        profile.save()
        removed_key = str(self.problem.pk)
        self.problem.delete()
        rebuild_contest_scores(self.contest.pk)
        profile.refresh_from_db()
        self.assertNotIn(removed_key, profile.acm_problems_status["contest_problems"])
        self.assertIn(str(unrelated.pk), profile.acm_problems_status["contest_problems"])
        self.assertFalse(ACMContestRank.objects.filter(contest=self.contest).exists())

    def test_ended_contest_ignores_old_frozen_cache(self):
        from django.urls import reverse
        self.contest.real_time_rank = False
        self.contest.save(update_fields=["real_time_rank"])
        attempt = self.submission(10)
        self.judge(attempt, judge_response())
        previous = list(ACMContestRank.objects.filter(contest=self.contest).select_related("user"))
        self.rejudge(attempt, judge_response(-1))
        cache.set(f"{CacheKey.contest_rank_cache}:{self.contest.pk}", previous)
        self.client.force_login(self.student)
        response = self.client.get(reverse("contest_rank_api"), {"contest_id": self.contest.pk, "limit": 10}).json()
        self.assertIsNone(response["error"])
        self.assertEqual(response["data"]["results"][0]["accepted_number"], 0)

    def test_failed_projection_rolls_back_verdict_and_rank_together(self):
        attempt = self.submission(10)
        self.judge(attempt, judge_response())
        with patch.object(UserProfile, "save", side_effect=RuntimeError("projection failed")), self.assertRaises(RuntimeError):
            self.rejudge(attempt, judge_response(-1))
        attempt.refresh_from_db()
        self.assertEqual(attempt.result, JudgeStatus.JUDGING)
        rank = ACMContestRank.objects.get(contest=self.contest, user=self.student)
        self.assertEqual((rank.accepted_number, rank.total_time), (1, 10))

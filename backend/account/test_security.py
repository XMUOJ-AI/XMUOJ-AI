from copy import deepcopy
from datetime import timedelta
from unittest import mock

from django.db import IntegrityError
from django.test import RequestFactory
from django.utils.timezone import now

from contest.models import Contest, ContestParticipation, OIContestRank
from contest.tests import DEFAULT_CONTEST_DATA
from utils.api.tests import APIClient, APITestCase
from utils.constants import CONTEST_PASSWORD_SESSION_KEY, ContestRuleType

from .middleware import SessionRecordMiddleware
from .models import User


class AccountPrivacyAPITest(APITestCase):
    def setUp(self):
        self.owner = self.create_admin(login=False)
        self.student = self.create_user("student", "student-password", login=False)
        data = dict(deepcopy(DEFAULT_CONTEST_DATA), password="", rule_type=ContestRuleType.OI,
                    start_time=now() - timedelta(hours=2), end_time=now() - timedelta(hours=1))
        self.contest = Contest.objects.create(created_by=self.owner, **data)
        ContestParticipation.objects.create(user=self.student, contest=self.contest, total_score=80)
        OIContestRank.objects.create(user=self.student, contest=self.contest, total_score=80)
        self.summary_url = self.reverse("user_contest_summary_api")
        self.detail_url = self.reverse("user_contest_detail_api")

    def test_anonymous_cannot_select_student_history(self):
        for url in (self.summary_url, self.detail_url):
            with self.subTest(url=url):
                self.assertFailed(self.client.get(url, {"username": self.student.username,
                                                        "contest_id": self.contest.id}))

    def test_history_is_limited_to_self_or_super_admin(self):
        self.create_user("other", "other-password")
        for url in (self.summary_url, self.detail_url):
            self.assertFailed(self.client.get(url, {"username": self.student.username,
                                                    "contest_id": self.contest.id}))
        self.client.force_login(self.student)
        self.assertSuccess(self.client.get(self.detail_url, {"contest_id": self.contest.id}))
        self.create_super_admin()
        self.assertSuccess(self.client.get(self.detail_url, {
            "username": self.student.username, "contest_id": self.contest.id}))

    def test_ongoing_oi_results_obey_hidden_rank_policy(self):
        self.contest.end_time = now() + timedelta(hours=1)
        self.contest.real_time_rank = False
        self.contest.save(update_fields=["end_time", "real_time_rank"])
        self.client.force_login(self.student)
        response = self.client.get(self.summary_url)
        self.assertSuccess(response)
        self.assertEqual(response.data["data"]["total"], 0)
        self.assertFailed(self.client.get(self.detail_url, {"contest_id": self.contest.id}))
        self.create_super_admin()
        response = self.client.get(self.detail_url, {
            "username": self.student.username, "contest_id": self.contest.id})
        self.assertSuccess(response)
        self.assertEqual(response.data["data"]["total_score"], 80)

    def test_public_rank_omits_private_profile_and_contest_history(self):
        profile = self.student.userprofile
        profile.real_name = "Private student name"
        profile.school = "Private class"
        profile.submission_number = 1
        profile.acm_problems_status = {"contest_problems": {"88": {"status": 0}}}
        profile.save()
        response = self.client.get(self.reverse("user_rank_api"))
        self.assertSuccess(response)
        row = response.data["data"]["results"][0]
        self.assertEqual(set(row), {"id", "user", "avatar", "mood", "accepted_number",
                                    "total_score", "submission_number"})
        self.assertIsNone(row["user"]["real_name"])

    def test_calibration_cannot_reveal_hidden_oi_score_before_finish(self):
        self.contest.end_time = now() + timedelta(hours=1)
        self.contest.real_time_rank = False
        self.contest.save(update_fields=["end_time", "real_time_rank"])
        self.client.force_login(self.student)
        url, data = self.reverse("contest_calibrate_api"), {"contest_id": self.contest.pk}
        with mock.patch("account.views.oj.ContestParticipation.calibrate_once") as calibrate:
            response = self.client.post(url, data)
            self.assertFailed(response, "No permission to get ranks")
            calibrate.assert_not_called()
        self.assertEqual(ContestParticipation.objects.get(user=self.student, contest=self.contest).total_score, 80)
        self.client.force_login(self.owner)
        self.assertSuccess(self.client.post(url, data))
        self.client.force_login(self.student)
        self.contest.end_time = now() - timedelta(minutes=1)
        self.contest.save(update_fields=["end_time"])
        self.assertSuccess(self.client.post(url, data))

    def test_calibration_requires_password_and_started_contest(self):
        self.contest.password = "contest-secret"
        self.contest.start_time = now() + timedelta(minutes=10)
        self.contest.end_time = now() + timedelta(hours=1)
        self.contest.real_time_rank = True
        self.contest.save(update_fields=["password", "start_time", "end_time", "real_time_rank"])
        self.client.force_login(self.student)
        url, data = self.reverse("contest_calibrate_api"), {"contest_id": self.contest.pk}
        with mock.patch("account.views.oj.ContestParticipation.calibrate_once") as calibrate:
            self.assertFailed(self.client.post(url, data), "Wrong password or password expired")
            session = self.client.session
            session[CONTEST_PASSWORD_SESSION_KEY] = {self.contest.pk: self.contest.password}
            session.save()
            self.assertFailed(self.client.post(url, data), "Contest has not started yet.")
            calibrate.assert_not_called()
        self.contest.start_time = now() - timedelta(minutes=10)
        self.contest.save(update_fields=["start_time"])
        self.assertSuccess(self.client.post(url, data))
        self.contest.password = "changed-secret"
        self.contest.save(update_fields=["password"])
        with mock.patch("account.views.oj.ContestParticipation.calibrate_once") as calibrate:
            self.assertFailed(self.client.post(url, data), "Wrong password or password expired")
            calibrate.assert_not_called()

    def test_calibration_error_does_not_expose_database_details(self):
        self.client.force_login(self.student)
        with mock.patch("account.views.oj.ContestParticipation.calibrate_once",
                        side_effect=RuntimeError("secret SQL student-code")), \
                self.assertLogs("account.views.oj", level="ERROR") as logs:
            response = self.client.post(self.reverse("contest_calibrate_api"), {"contest_id": self.contest.id})
        self.assertFailed(response)
        self.assertEqual(response.data["data"], "Calibration failed; please try again later")
        self.assertNotIn("secret SQL", " ".join(logs.output))
        self.assertIn("RuntimeError", " ".join(logs.output))


class AccountSessionSecurityTest(APITestCase):
    def test_current_session_can_be_revoked_without_resaving_deleted_session(self):
        self.create_user("student", "student-password")
        self.client.get(self.reverse("user_profile_api"))
        key = self.client.session.session_key
        response = self.client.delete(self.reverse("session_management_api") + "?session_key=" + key)
        self.assertSuccess(response)
        self.assertIsNone(self.client.get(self.reverse("user_profile_api")).data["data"])

    def test_foreign_session_is_not_deleted_on_denied_request(self):
        victim = self.create_user("victim", "victim-password", login=False)
        victim_client = APIClient()
        victim_client.force_login(victim)
        victim_key = victim_client.session.session_key
        self.create_user("attacker", "attacker-password")
        response = self.client.delete(self.reverse("session_management_api") + "?session_key=" + victim_key)
        self.assertFailed(response)
        response = victim_client.get(self.reverse("user_profile_api"))
        self.assertSuccess(response)
        self.assertEqual(response.data["data"]["user"]["id"], victim.id)

    def test_owned_session_can_be_revoked(self):
        user = self.create_user("student", "student-password")
        other_client = APIClient()
        other_client.force_login(user)
        other_client.get(self.reverse("user_profile_api"))
        other_key = other_client.session.session_key
        response = self.client.delete(self.reverse("session_management_api") + "?session_key=" + other_key)
        self.assertSuccess(response)
        self.assertIsNone(other_client.get(self.reverse("user_profile_api")).data["data"])

    def test_disabled_session_loses_profile_and_admin_access(self):
        user = self.create_admin()
        User.objects.filter(pk=user.pk).update(is_disabled=True)
        response = self.client.post(self.reverse("contest_admin_api"), deepcopy(DEFAULT_CONTEST_DATA))
        self.assertFailed(response)
        self.assertFalse(Contest.objects.exists())
        self.assertIsNone(self.client.get(self.reverse("user_profile_api")).data["data"])

    def test_session_record_preserves_concurrent_account_and_session_changes(self):
        user = self.create_user("student", "old-password", login=False)
        stale_user = User.objects.get(pk=user.pk)
        user.set_password("new-password")
        user.is_disabled = True
        user.session_keys = ["other-session"]
        user.save(update_fields=["password", "is_disabled", "session_keys"])

        class Session(dict):
            session_key = "new-session"

        request = RequestFactory().get("/api/profile")
        request.user = stale_user
        request.session = Session()
        SessionRecordMiddleware(lambda request: None).process_request(request)
        user.refresh_from_db()
        self.assertTrue(user.check_password("new-password"))
        self.assertTrue(user.is_disabled)
        self.assertEqual(set(user.session_keys), {"other-session", "new-session"})


class PasswordResetErrorPrivacyTest(APITestCase):
    def test_bulk_reset_conflicts_do_not_expose_sql_or_raise_index_error(self):
        self.create_super_admin()
        self.client.get(self.reverse("user_profile_api"))
        student = self.create_user("target-student", "old-password", login=False)
        profile = student.userprofile
        profile.school = "target-class"
        profile.save(update_fields=["school"])
        for match_type in ("type_username", "type_school"):
            for message in ("secret SQL", "conflict\nsecret SQL"):
                with self.subTest(match_type=match_type, message=message), \
                        mock.patch("account.views.admin.User.save", side_effect=IntegrityError(message)):
                    response = self.client.post(self.reverse("change_userpassword_api"), {
                        "suffix": "new-password", "match_type": match_type,
                        "right_length": 0, "target_name": "target"})
                self.assertFailed(response)
                self.assertEqual(response.data["data"], "Password update conflicted; refresh and retry")

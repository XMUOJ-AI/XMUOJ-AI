from copy import deepcopy

from django.conf import settings
from django.contrib import auth
from otpauth import OtpAuth

from account.models import User
from judge.models import JudgeDispatch
from problem.models import Problem
from problem.tests import DEFAULT_PROBLEM_DATA
from submission.models import Submission
from utils.api.tests import APIClient, APITestCase
from utils.cache import cache


class PluginSessionAuthTests(APITestCase):
    def setUp(self):
        self.user = self.create_user("plugin-student", "student-password", login=False)
        self.client = APIClient(enforce_csrf_checks=True)
        self.credentials = {"username": self.user.username, "password": "student-password"}
        self.login_url = self.reverse("plugin_login_api")
        self.logout_url = self.reverse("plugin_logout_api")
        self.bootstrap_url = self.reverse("plugin_bootstrap_api")
        self.submission_url = self.reverse("plugin_submission_api")

    def bootstrap(self, client=None):
        client = client or self.client
        response = client.get(self.bootstrap_url)
        self.assertSuccess(response)
        self.assertIn(settings.CSRF_COOKIE_NAME, client.cookies)
        return response.data["data"]

    def login(self, client=None, credentials=None):
        client = client or self.client
        token = self.bootstrap(client)["csrf_token"]
        response = client.post(self.login_url, credentials or self.credentials, HTTP_X_CSRFTOKEN=token)
        self.assertSuccess(response)
        return response.data["data"]

    def test_login_rotates_anonymous_session_and_allows_query_and_submission(self):
        session = self.client.session
        session["anonymous_marker"] = "retained"
        session.save()
        old_key = session.session_key
        login = self.login()
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertFalse(session.exists(old_key))
        self.assertEqual(self.client.session[auth.SESSION_KEY], str(self.user.pk))
        self.assertEqual(self.client.session["anonymous_marker"], "retained")
        self.assertEqual(self.bootstrap()["user"]["id"], self.user.pk)

        data = deepcopy(DEFAULT_PROBLEM_DATA)
        data.pop("tags")
        problem = Problem.objects.create(created_by=self.user, **data)
        cache.delete(str(self.user.pk))
        self.addCleanup(cache.delete, str(self.user.pk))
        response = self.client.post(self.submission_url, {
            "problem_id": problem.pk, "language": "C", "code": "int main(void) { return 0; }",
        }, HTTP_X_CSRFTOKEN=login["csrf_token"])
        self.assertSuccess(response)
        submission = Submission.objects.get(pk=response.data["data"]["submission_id"])
        self.assertEqual(submission.user_id, self.user.pk)
        self.assertEqual(JudgeDispatch.objects.get(submission=submission).status, "queued")
        self.assertSuccess(self.client.get(self.submission_url, {"submission_id": submission.pk}))

        anonymous = APIClient(enforce_csrf_checks=True)
        self.assertFailed(anonymous.get(self.submission_url, {"submission_id": submission.pk},
                                        HTTP_AUTHORIZATION="Bearer " + login["token"]))
        sso = anonymous.post(self.reverse("sso_api"), {"token": login["token"]})
        self.assertSuccess(sso)
        self.assertEqual(sso.data["data"]["username"], self.user.username)

    def test_login_submission_and_logout_require_csrf_and_login_rotates_csrf(self):
        old_token = self.bootstrap()["csrf_token"]
        response = self.client.post(self.login_url, self.credentials)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(auth.SESSION_KEY, self.client.session)
        login = self.login()
        for url, data in ((self.login_url, self.credentials), (self.submission_url, {}), (self.logout_url, {})):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 403)
        self.assertEqual(self.client.post(self.logout_url, {}, HTTP_X_CSRFTOKEN=old_token).status_code, 403)
        self.assertEqual(self.bootstrap()["user"]["id"], self.user.pk)
        self.assertSuccess(self.client.post(self.logout_url, {}, HTTP_X_CSRFTOKEN=login["csrf_token"]))

    def test_existing_web_session_relogin_and_account_switch(self):
        self.assertSuccess(self.client.post(self.reverse("user_login_api"), self.credentials))
        session = self.client.session
        original_key = session.session_key
        self.assertEqual(self.bootstrap()["user"]["id"], self.user.pk)
        self.login()
        self.assertEqual(self.client.session.session_key, original_key)
        token = self.bootstrap()["csrf_token"]
        self.assertFailed(self.client.post(self.login_url, dict(self.credentials, password="wrong"),
                                           HTTP_X_CSRFTOKEN=token))
        self.assertEqual(self.bootstrap()["user"]["id"], self.user.pk)

        other = self.create_user("other-plugin-student", "other-password", login=False)
        login = self.login(credentials={"username": other.username, "password": "other-password"})
        self.assertEqual(login["user"]["id"], other.pk)
        self.assertNotEqual(self.client.session.session_key, original_key)
        self.assertFalse(session.exists(original_key))
        self.assertEqual(self.bootstrap()["user"]["id"], other.pk)

    def test_disabled_login_and_existing_session_are_rejected(self):
        self.login()
        session = self.client.session
        old_key = session.session_key
        User.objects.filter(pk=self.user.pk).update(is_disabled=True)
        self.assertIsNone(self.bootstrap()["user"])
        self.assertFalse(session.exists(old_key))
        token = self.bootstrap()["csrf_token"]
        response = self.client.post(self.login_url, self.credentials, HTTP_X_CSRFTOKEN=token)
        self.assertFailed(response, "Your account has been disabled")
        self.assertNotIn(auth.SESSION_KEY, self.client.session)
        self.assertFailed(self.client.get(self.submission_url, {"submission_id": "unavailable"}))

    def test_two_factor_login_requires_valid_code_before_creating_session(self):
        self.user.two_factor_auth = True
        self.user.tfa_token = "plugin-test-two-factor-secret"
        self.user.save(update_fields=["two_factor_auth", "tfa_token"])
        token = self.bootstrap()["csrf_token"]
        for credentials, error in ((self.credentials, "tfa_required"),
                                   (dict(self.credentials, tfa_code="invalid"), "Invalid two factor verification code")):
            with self.subTest(error=error):
                response = self.client.post(self.login_url, credentials, HTTP_X_CSRFTOKEN=token)
                self.assertFailed(response, error)
                self.assertNotIn(auth.SESSION_KEY, self.client.session)
        login = self.login(credentials=dict(self.credentials, tfa_code=str(OtpAuth(self.user.tfa_token).totp())))
        self.assertEqual(login["user"]["id"], self.user.pk)

    def test_logout_revokes_current_session_and_sso_token_only(self):
        login = self.login()
        other_client = APIClient(enforce_csrf_checks=True)
        self.login(client=other_client)
        session = self.client.session
        old_key = session.session_key
        self.assertSuccess(self.client.post(self.logout_url, {}, HTTP_X_CSRFTOKEN=login["csrf_token"]))
        self.assertFalse(session.exists(old_key))
        self.assertNotIn(auth.SESSION_KEY, self.client.session)
        self.assertIsNone(self.bootstrap()["user"])
        self.assertFailed(self.client.get(self.submission_url, {"submission_id": "unavailable"}))
        self.assertEqual(self.bootstrap(other_client)["user"]["id"], self.user.pk)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.auth_token)

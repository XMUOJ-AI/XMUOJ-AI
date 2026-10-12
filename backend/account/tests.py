import io
import os
import stat
import tempfile
import time
import zipfile
from xml.etree import ElementTree

from unittest import mock
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
from copy import deepcopy

from django.contrib import auth
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils.timezone import now
from otpauth import OtpAuth

from utils.api.tests import APIClient, APITestCase
from utils.shortcuts import rand_str
from options.options import SysOptions
from problem.models import Problem, ProblemRuleType
from utils.constants import Difficulty
from submission.models import JudgeStatus

from .models import AdminType, ProblemPermission, User, UserProfile, UserCredentialExport
from .credential_exports import EXPORT_LIFETIME, export_path
from .decorators import super_admin_required
from utils.constants import ContestRuleType


def credential_test_directory(test):
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    override = test.settings(USER_CREDENTIAL_EXPORT_DIR=directory.name)
    override.enable()
    test.addCleanup(override.disable)
    return directory.name


def workbook_credentials(content):
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        strings = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        values = ["".join(node.itertext()) for node in strings]
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        rows = sheet.findall("m:sheetData/m:row", namespace)[1:]
        return dict(tuple(values[int(cell.find("m:v", namespace).text)] for cell in row) for row in rows)


class PermissionDecoratorTest(APITestCase):
    def setUp(self):
        self.regular_user = User.objects.create(username="regular_user")
        self.admin = User.objects.create(username="admin")
        self.super_admin = User.objects.create(username="super_admin")
        self.request = mock.MagicMock()
        self.request.user.is_authenticated = mock.MagicMock()

    def test_login_required(self):
        self.request.user.is_authenticated.return_value = False

    def test_admin_required(self):
        pass

    def test_super_admin_required(self):
        pass


class DuplicateUserCheckAPITest(APITestCase):
    def setUp(self):
        user = self.create_user("test", "test123", login=False)
        user.email = "test@test.com"
        user.save()
        self.url = self.reverse("check_username_or_email")

    def test_duplicate_username(self):
        resp = self.client.post(self.url, data={"username": "test"})
        data = resp.data["data"]
        self.assertEqual(data["username"], True)
        resp = self.client.post(self.url, data={"username": "Test"})
        self.assertEqual(resp.data["data"]["username"], True)

    def test_ok_username(self):
        resp = self.client.post(self.url, data={"username": "test1"})
        data = resp.data["data"]
        self.assertFalse(data["username"])

    def test_duplicate_email(self):
        resp = self.client.post(self.url, data={"email": "test@test.com"})
        self.assertEqual(resp.data["data"]["email"], True)
        resp = self.client.post(self.url, data={"email": "Test@Test.com"})
        self.assertTrue(resp.data["data"]["email"])

    def test_ok_email(self):
        resp = self.client.post(self.url, data={"email": "aa@test.com"})
        self.assertFalse(resp.data["data"]["email"])


class TFARequiredCheckAPITest(APITestCase):
    def setUp(self):
        self.url = self.reverse("tfa_required_check")
        self.create_user("test", "test123", login=False)

    def test_not_required_tfa(self):
        resp = self.client.post(self.url, data={"username": "test"})
        self.assertSuccess(resp)
        self.assertEqual(resp.data["data"]["result"], False)

    def test_required_tfa(self):
        user = User.objects.first()
        user.two_factor_auth = True
        user.save()
        resp = self.client.post(self.url, data={"username": "test"})
        self.assertEqual(resp.data["data"]["result"], True)


class UserLoginAPITest(APITestCase):
    def setUp(self):
        self.username = self.password = "test"
        self.user = self.create_user(username=self.username, password=self.password, login=False)
        self.login_url = self.reverse("user_login_api")

    def _set_tfa(self):
        self.user.two_factor_auth = True
        tfa_token = rand_str(32)
        self.user.tfa_token = tfa_token
        self.user.save()
        return tfa_token

    def test_login_with_correct_info(self):
        response = self.client.post(self.login_url,
                                    data={"username": self.username, "password": self.password})
        self.assertDictEqual(response.data, {"error": None, "data": "Succeeded"})

        user = auth.get_user(self.client)
        self.assertTrue(user.is_authenticated)

    def test_login_with_correct_info_upper_username(self):
        resp = self.client.post(self.login_url, data={"username": self.username.upper(), "password": self.password})
        self.assertDictEqual(resp.data, {"error": None, "data": "Succeeded"})
        user = auth.get_user(self.client)
        self.assertTrue(user.is_authenticated)

    def test_login_with_wrong_info(self):
        response = self.client.post(self.login_url,
                                    data={"username": self.username, "password": "invalid_password"})
        self.assertDictEqual(response.data, {"error": "error", "data": "Invalid username or password"})

        user = auth.get_user(self.client)
        self.assertFalse(user.is_authenticated)

    def test_tfa_login(self):
        token = self._set_tfa()
        code = OtpAuth(token).totp()
        if len(str(code)) < 6:
            code = (6 - len(str(code))) * "0" + str(code)
        response = self.client.post(self.login_url,
                                    data={"username": self.username,
                                          "password": self.password,
                                          "tfa_code": code})
        self.assertDictEqual(response.data, {"error": None, "data": "Succeeded"})

        user = auth.get_user(self.client)
        self.assertTrue(user.is_authenticated)

    def test_tfa_login_wrong_code(self):
        self._set_tfa()
        response = self.client.post(self.login_url,
                                    data={"username": self.username,
                                          "password": self.password,
                                          "tfa_code": "qqqqqq"})
        self.assertDictEqual(response.data, {"error": "error", "data": "Invalid two factor verification code"})

        user = auth.get_user(self.client)
        self.assertFalse(user.is_authenticated)

    def test_tfa_login_without_code(self):
        self._set_tfa()
        response = self.client.post(self.login_url,
                                    data={"username": self.username,
                                          "password": self.password})
        self.assertDictEqual(response.data, {"error": "error", "data": "tfa_required"})

        user = auth.get_user(self.client)
        self.assertFalse(user.is_authenticated)

    def test_user_disabled(self):
        self.user.is_disabled = True
        self.user.save()
        resp = self.client.post(self.login_url, data={"username": self.username,
                                                      "password": self.password})
        self.assertDictEqual(resp.data, {"error": "error", "data": "Your account has been disabled"})


class CaptchaTest(APITestCase):
    def _set_captcha(self, session):
        captcha = rand_str(4)
        session["_django_captcha_key"] = captcha
        session["_django_captcha_expires_time"] = int(time.time()) + 30
        session.save()
        return captcha


class UserRegisterAPITest(CaptchaTest):
    def setUp(self):
        self.client = APIClient()
        self.register_url = self.reverse("user_register_api")
        self.captcha = rand_str(4)

        self.data = {"username": "test_user", "password": "testuserpassword",
                     "real_name": "real_name", "email": "test@qduoj.com",
                     "captcha": self._set_captcha(self.client.session)}

    def test_website_config_limit(self):
        SysOptions.allow_register = False
        resp = self.client.post(self.register_url, data=self.data)
        self.assertDictEqual(resp.data, {"error": "error", "data": "Register function has been disabled by admin"})

    def test_invalid_captcha(self):
        self.data["captcha"] = "****"
        response = self.client.post(self.register_url, data=self.data)
        self.assertDictEqual(response.data, {"error": "error", "data": "Invalid captcha"})

        self.data.pop("captcha")
        response = self.client.post(self.register_url, data=self.data)
        self.assertTrue(response.data["error"] is not None)

    def test_register_with_correct_info(self):
        response = self.client.post(self.register_url, data=self.data)
        self.assertDictEqual(response.data, {"error": None, "data": "Succeeded"})

    def test_username_already_exists(self):
        self.test_register_with_correct_info()

        self.data["captcha"] = self._set_captcha(self.client.session)
        self.data["email"] = "test1@qduoj.com"
        response = self.client.post(self.register_url, data=self.data)
        self.assertDictEqual(response.data, {"error": "error", "data": "Username already exists"})

    def test_email_already_exists(self):
        self.test_register_with_correct_info()

        self.data["captcha"] = self._set_captcha(self.client.session)
        self.data["username"] = "test_user1"
        response = self.client.post(self.register_url, data=self.data)
        self.assertDictEqual(response.data, {"error": "error", "data": "Email already exists"})


class SessionManagementAPITest(APITestCase):
    def setUp(self):
        self.create_user("test", "test123")
        self.url = self.reverse("session_management_api")
        # launch a request to provide session data
        login_url = self.reverse("user_login_api")
        self.client.post(login_url, data={"username": "test", "password": "test123"})

    def test_get_sessions(self):
        resp = self.client.get(self.url)
        self.assertSuccess(resp)
        data = resp.data["data"]
        self.assertEqual(len(data), 1)

    # def test_delete_session_key(self):
    #     resp = self.client.delete(self.url + "?session_key=" + self.session_key)
    #     self.assertSuccess(resp)

    def test_delete_session_with_invalid_key(self):
        resp = self.client.delete(self.url + "?session_key=aaaaaaaaaa")
        self.assertDictEqual(resp.data, {"error": "error", "data": "Invalid session_key"})


class UserProfileAPITest(APITestCase):
    def setUp(self):
        self.url = self.reverse("user_profile_api")

    def test_get_profile_without_login(self):
        resp = self.client.get(self.url)
        self.assertDictEqual(resp.data, {"error": None, "data": None})

    def test_get_profile(self):
        self.create_user("test", "test123")
        resp = self.client.get(self.url)
        self.assertSuccess(resp)

    def test_update_profile(self):
        self.create_user("test", "test123")
        update_data = {"real_name": "zemal", "submission_number": 233, "language": "en-US"}
        resp = self.client.put(self.url, data=update_data)
        self.assertSuccess(resp)
        data = resp.data["data"]
        self.assertEqual(data["real_name"], "zemal")
        self.assertEqual(data["submission_number"], 0)
        self.assertEqual(data["language"], "en-US")


class TwoFactorAuthAPITest(APITestCase):
    def setUp(self):
        self.url = self.reverse("two_factor_auth_api")
        self.create_user("test", "test123")

    def _get_tfa_code(self):
        user = User.objects.first()
        code = OtpAuth(user.tfa_token).totp()
        if len(str(code)) < 6:
            code = (6 - len(str(code))) * "0" + str(code)
        return code

    def test_get_image(self):
        resp = self.client.get(self.url)
        self.assertSuccess(resp)

    def test_open_tfa_with_invalid_code(self):
        self.test_get_image()
        resp = self.client.post(self.url, data={"code": "000000"})
        self.assertDictEqual(resp.data, {"error": "error", "data": "Invalid code"})

    def test_open_tfa_with_correct_code(self):
        self.test_get_image()
        code = self._get_tfa_code()
        resp = self.client.post(self.url, data={"code": code})
        self.assertSuccess(resp)
        user = User.objects.first()
        self.assertEqual(user.two_factor_auth, True)

    def test_close_tfa_with_invalid_code(self):
        self.test_open_tfa_with_correct_code()
        resp = self.client.post(self.url, data={"code": "000000"})
        self.assertDictEqual(resp.data, {"error": "error", "data": "Invalid code"})

    def test_close_tfa_with_correct_code(self):
        self.test_open_tfa_with_correct_code()
        code = self._get_tfa_code()
        resp = self.client.put(self.url, data={"code": code})
        self.assertSuccess(resp)
        user = User.objects.first()
        self.assertEqual(user.two_factor_auth, False)


@mock.patch("account.views.oj.send_email_async.send")
class ApplyResetPasswordAPITest(CaptchaTest):
    def setUp(self):
        self.create_user("test", "test123", login=False)
        user = User.objects.first()
        user.email = "test@oj.com"
        user.save()
        self.url = self.reverse("apply_reset_password_api")
        self.data = {"email": "test@oj.com", "captcha": self._set_captcha(self.client.session)}

    def _refresh_captcha(self):
        self.data["captcha"] = self._set_captcha(self.client.session)

    def test_apply_reset_password(self, send_email_send):
        resp = self.client.post(self.url, data=self.data)
        self.assertSuccess(resp)
        send_email_send.assert_called()

    def test_apply_reset_password_twice_in_20_mins(self, send_email_send):
        self.test_apply_reset_password()
        send_email_send.reset_mock()
        self._refresh_captcha()
        resp = self.client.post(self.url, data=self.data)
        self.assertDictEqual(resp.data, {"error": "error", "data": "You can only reset password once per 20 minutes"})
        send_email_send.assert_not_called()

    def test_apply_reset_password_again_after_20_mins(self, send_email_send):
        self.test_apply_reset_password()
        user = User.objects.first()
        user.reset_password_token_expire_time = now() - timedelta(minutes=21)
        user.save()
        self._refresh_captcha()
        self.test_apply_reset_password()


class ResetPasswordAPITest(CaptchaTest):
    def setUp(self):
        self.create_user("test", "test123", login=False)
        self.url = self.reverse("reset_password_api")
        user = User.objects.first()
        user.reset_password_token = "online_judge?"
        user.reset_password_token_expire_time = now() + timedelta(minutes=20)
        user.save()
        self.data = {"token": user.reset_password_token,
                     "captcha": self._set_captcha(self.client.session),
                     "password": "test456"}

    def test_reset_password_with_correct_token(self):
        resp = self.client.post(self.url, data=self.data)
        self.assertSuccess(resp)
        self.assertTrue(self.client.login(username="test", password="test456"))

    def test_reset_password_with_invalid_token(self):
        self.data["token"] = "aaaaaaaaaaa"
        resp = self.client.post(self.url, data=self.data)
        self.assertDictEqual(resp.data, {"error": "error", "data": "Token does not exist"})

    def test_reset_password_with_expired_token(self):
        user = User.objects.first()
        user.reset_password_token_expire_time = now() - timedelta(seconds=30)
        user.save()
        resp = self.client.post(self.url, data=self.data)
        self.assertDictEqual(resp.data, {"error": "error", "data": "Token has expired"})


class UserChangeEmailAPITest(APITestCase):
    def setUp(self):
        self.url = self.reverse("user_change_email_api")
        self.user = self.create_user("test", "test123")
        self.new_mail = "test@oj.com"
        self.data = {"password": "test123", "new_email": self.new_mail}

    def test_change_email_success(self):
        resp = self.client.post(self.url, data=self.data)
        self.assertSuccess(resp)

    def test_wrong_password(self):
        self.data["password"] = "aaaa"
        resp = self.client.post(self.url, data=self.data)
        self.assertDictEqual(resp.data, {"error": "error", "data": "Wrong password"})

    def test_duplicate_email(self):
        u = self.create_user("aa", "bb", login=False)
        u.email = self.new_mail
        u.save()
        resp = self.client.post(self.url, data=self.data)
        self.assertDictEqual(resp.data, {"error": "error", "data": "The email is owned by other account"})


class UserChangePasswordAPITest(APITestCase):
    def setUp(self):
        self.url = self.reverse("user_change_password_api")

        # Create user at first
        self.username = "test_user"
        self.old_password = "testuserpassword"
        self.new_password = "new_password"
        self.user = self.create_user(username=self.username, password=self.old_password, login=False)

        self.data = {"old_password": self.old_password, "new_password": self.new_password}

    def _get_tfa_code(self):
        user = User.objects.first()
        code = OtpAuth(user.tfa_token).totp()
        if len(str(code)) < 6:
            code = (6 - len(str(code))) * "0" + str(code)
        return code

    def test_login_required(self):
        response = self.client.post(self.url, data=self.data)
        self.assertEqual(response.data, {"error": "permission-denied", "data": "Please login first"})

    def test_valid_ola_password(self):
        self.assertTrue(self.client.login(username=self.username, password=self.old_password))
        response = self.client.post(self.url, data=self.data)
        self.assertEqual(response.data, {"error": None, "data": "Succeeded"})
        self.assertTrue(self.client.login(username=self.username, password=self.new_password))

    def test_invalid_old_password(self):
        self.assertTrue(self.client.login(username=self.username, password=self.old_password))
        self.data["old_password"] = "invalid"
        response = self.client.post(self.url, data=self.data)
        self.assertEqual(response.data, {"error": "error", "data": "Invalid old password"})

    def test_tfa_code_required(self):
        self.user.two_factor_auth = True
        self.user.tfa_token = "tfa_token"
        self.user.save()
        self.assertTrue(self.client.login(username=self.username, password=self.old_password))
        self.data["tfa_code"] = rand_str(6)
        resp = self.client.post(self.url, data=self.data)
        self.assertEqual(resp.data, {"error": "error", "data": "Invalid two factor verification code"})

        self.data["tfa_code"] = self._get_tfa_code()
        resp = self.client.post(self.url, data=self.data)
        self.assertSuccess(resp)


class UserRankAPITest(APITestCase):
    def setUp(self):
        self.url = self.reverse("user_rank_api")
        self.create_user("test1", "test123", login=False)
        self.create_user("test2", "test123", login=False)
        test1 = User.objects.get(username="test1")
        profile1 = test1.userprofile
        profile1.submission_number = 10
        profile1.accepted_number = 10
        profile1.total_score = 240
        profile1.save()

        test2 = User.objects.get(username="test2")
        profile2 = test2.userprofile
        profile2.submission_number = 15
        profile2.accepted_number = 10
        profile2.total_score = 700
        profile2.save()

    def test_get_acm_rank(self):
        resp = self.client.get(self.url, data={"rule": ContestRuleType.ACM})
        self.assertSuccess(resp)
        data = resp.data["data"]["results"]
        self.assertEqual(data[0]["user"]["username"], "test1")
        self.assertEqual(data[1]["user"]["username"], "test2")

    def test_get_oi_rank(self):
        resp = self.client.get(self.url, data={"rule": ContestRuleType.OI})
        self.assertSuccess(resp)
        data = resp.data["data"]["results"]
        self.assertEqual(data[0]["user"]["username"], "test2")
        self.assertEqual(data[1]["user"]["username"], "test1")

    def test_admin_role_filted(self):
        self.create_admin("admin", "admin123")
        admin = User.objects.get(username="admin")
        profile1 = admin.userprofile
        profile1.submission_number = 20
        profile1.accepted_number = 5
        profile1.total_score = 300
        profile1.save()
        resp = self.client.get(self.url, data={"rule": ContestRuleType.ACM})
        self.assertSuccess(resp)
        self.assertEqual(len(resp.data["data"]), 2)

        resp = self.client.get(self.url, data={"rule": ContestRuleType.OI})
        self.assertSuccess(resp)
        self.assertEqual(len(resp.data["data"]), 2)


class ProfileProblemDisplayIDRefreshAPITest(APITestCase):
    def setUp(self):
        self.user = self.create_user("refresh_user", "refresh_pass", login=True)
        self.url = self.reverse("display_id_fresh")

    def _create_public_problem(self, display_id, rule_type=ProblemRuleType.ACM):
        return Problem.objects.create(
            _id=display_id,
            contest=None,
            title=f"Problem {display_id}",
            description="d",
            input_description="i",
            output_description="o",
            samples=[{"input": "1", "output": "1"}],
            test_case_id="tc",
            test_case_score=[],
            hint="",
            languages=["Python3"],
            template={},
            created_by=self.user,
            time_limit=1000,
            memory_limit=128,
            rule_type=rule_type,
            visible=True,
            difficulty=Difficulty.LOW,
            source="",
            share_submission=False
        )

    def test_refresh_filters_invalid_public_problems_and_recomputes_stats(self):
        acm_valid = self._create_public_problem("ACM100")
        oi_valid = self._create_public_problem("OI100", rule_type=ProblemRuleType.OI)
        profile = self.user.userprofile

        profile.acm_problems_status = {
            "problems": {
                str(acm_valid.id): {"status": JudgeStatus.ACCEPTED, "_id": "OLD"},
                "999999": {"status": JudgeStatus.ACCEPTED, "_id": "STALE"}
            },
            "contest_problems": {}
        }
        profile.oi_problems_status = {
            "problems": {
                str(oi_valid.id): {"status": JudgeStatus.ACCEPTED, "_id": "OLD", "score": 300},
                "888888": {"status": JudgeStatus.WRONG_ANSWER, "_id": "STALE", "score": 999}
            },
            "contest_problems": {}
        }
        profile.accepted_number = 999
        profile.total_score = 999
        profile.save(update_fields=["acm_problems_status", "oi_problems_status", "accepted_number", "total_score"])

        resp = self.client.get(self.url)
        self.assertSuccess(resp)
        self.assertEqual(resp.data["data"]["removed"], 2)
        self.user.refresh_from_db()
        profile = self.user.userprofile

        acm_problems = profile.acm_problems_status.get("problems", {})
        oi_problems = profile.oi_problems_status.get("problems", {})
        self.assertEqual(set(acm_problems.keys()), {str(acm_valid.id)})
        self.assertEqual(set(oi_problems.keys()), {str(oi_valid.id)})
        self.assertEqual(acm_problems[str(acm_valid.id)]["_id"], acm_valid._id)
        self.assertEqual(oi_problems[str(oi_valid.id)]["_id"], oi_valid._id)
        self.assertEqual(profile.accepted_number, 2)
        self.assertEqual(profile.total_score, 300)


class AdminUserTest(APITestCase):
    def setUp(self):
        self.export_directory = credential_test_directory(self)
        self.user = self.create_super_admin(login=True)
        self.username = self.password = "test"
        self.regular_user = self.create_user(username=self.username, password=self.password, login=False)
        self.url = self.reverse("user_admin_api")
        self.data = {"id": self.regular_user.id, "username": self.username, "real_name": "test_name",
                     "email": "test@qq.com", "admin_type": AdminType.REGULAR_USER,
                     "problem_permission": ProblemPermission.OWN, "open_api": True,
                     "two_factor_auth": False, "is_disabled": False}

    def test_user_list(self):
        response = self.client.get(self.url)
        self.assertSuccess(response)

    def test_edit_user_successfully(self):
        response = self.client.put(self.url, data=self.data)
        self.assertSuccess(response)
        resp_data = response.data["data"]
        self.assertEqual(resp_data["username"], self.username)
        self.assertEqual(resp_data["email"], "test@qq.com")
        self.assertEqual(resp_data["open_api"], True)
        self.assertEqual(resp_data["two_factor_auth"], False)
        self.assertEqual(resp_data["is_disabled"], False)
        self.assertEqual(resp_data["problem_permission"], ProblemPermission.NONE)

        self.assertTrue(self.regular_user.check_password("test"))

    def test_edit_user_password(self):
        data = self.data
        new_password = "testpassword"
        data["password"] = new_password
        response = self.client.put(self.url, data=data)
        self.assertSuccess(response)
        user = User.objects.get(id=self.regular_user.id)
        self.assertFalse(user.check_password(self.password))
        self.assertTrue(user.check_password(new_password))

    def test_edit_user_tfa(self):
        data = self.data
        self.assertIsNone(self.regular_user.tfa_token)
        data["two_factor_auth"] = True
        response = self.client.put(self.url, data=data)
        self.assertSuccess(response)
        resp_data = response.data["data"]
        # if `tfa_token` is None, a new value will be generated
        self.assertTrue(resp_data["two_factor_auth"])
        token = User.objects.get(id=self.regular_user.id).tfa_token
        self.assertIsNotNone(token)

        response = self.client.put(self.url, data=data)
        self.assertSuccess(response)
        resp_data = response.data["data"]
        # if `tfa_token` is not None, the value is not changed
        self.assertTrue(resp_data["two_factor_auth"])
        self.assertEqual(User.objects.get(id=self.regular_user.id).tfa_token, token)

    def test_edit_user_openapi(self):
        data = self.data
        self.assertIsNone(self.regular_user.open_api_appkey)
        data["open_api"] = True
        response = self.client.put(self.url, data=data)
        self.assertSuccess(response)
        resp_data = response.data["data"]
        # if `open_api_appkey` is None, a new value will be generated
        self.assertTrue(resp_data["open_api"])
        key = User.objects.get(id=self.regular_user.id).open_api_appkey
        self.assertIsNotNone(key)

        response = self.client.put(self.url, data=data)
        self.assertSuccess(response)
        resp_data = response.data["data"]
        # if `openapi_app_key` is not None, the value is not changed
        self.assertTrue(resp_data["open_api"])
        self.assertEqual(User.objects.get(id=self.regular_user.id).open_api_appkey, key)

    def test_import_users(self):
        data = {"users": [["user1", "Student One", "Class A"],
                          ["user2", "Student Two", "Class B"]]
                }
        resp = self.client.post(self.url, data)
        self.assertSuccess(resp)
        download = self.client.get(self.reverse("generate_user_api"), {"file_id": resp.data["data"]["file_id"]})
        passwords = workbook_credentials(download.content)
        self.assertEqual(len(set(passwords.values())), 2)
        self.assertEqual(User.objects.all().count(), 4)
        for username, real_name, classroom in data["users"]:
            user = User.objects.get(username=username)
            self.assertFalse(user.check_password("123456"))
            self.assertEqual(len(passwords[username]), 24)
            self.assertTrue(user.check_password(passwords[username]))
            self.assertNotEqual(user.password, passwords[username])
            self.assertIsNone(user.email)
            self.assertEqual(user.userprofile.real_name, real_name)
            self.assertEqual(user.userprofile.school, classroom)
            self.assertEqual(user.userprofile.language, "zh-CN")

    def test_import_duplicate_user(self):
        data = {"users": [["user1", "Student One", "Class A"],
                          ["user1", "Student One", "Class A"]]
                }
        resp = self.client.post(self.url, data)
        self.assertFailed(resp, "Duplicate usernames in import")
        # no user is created
        self.assertEqual(User.objects.all().count(), 2)

    def test_import_normalizes_new_names_and_matches_legacy_case_without_reset(self):
        self.regular_user.username = "LegacyStudent"
        self.regular_user.save(update_fields=["username"])
        password_hash = self.regular_user.password
        data = {"users": [["LEGACYSTUDENT", "Keep Existing Name", "New Class"], ["NewStudent", "New", "A"]]}
        response = self.client.post(self.url, data)
        self.assertSuccess(response)
        self.regular_user.refresh_from_db()
        self.assertEqual(self.regular_user.username, "LegacyStudent")
        self.assertEqual(self.regular_user.password, password_hash)
        self.assertEqual(self.regular_user.userprofile.school, "New Class")
        self.assertEqual(User.objects.filter(username__iexact="legacystudent").count(), 1)
        canonical = {"users": [[row[0].lower(), *row[1:]] for row in data["users"]]}
        replay = self.client.post(self.url, canonical)
        self.assertEqual(replay.data, response.data)
        file_id = response.data["data"]["file_id"]
        passwords = workbook_credentials(self.client.get(self.reverse("generate_user_api"), {"file_id": file_id}).content)
        self.assertEqual(list(passwords), ["newstudent"])
        self.client.logout()
        self.assertSuccess(self.client.post(self.reverse("user_login_api"), {"username": "NEWSTUDENT", "password": passwords["newstudent"]}))

    def test_import_rejects_same_batch_case_variants_before_any_changes(self):
        before_school = self.regular_user.userprofile.school
        rows = [[self.username, "Existing", "Changed"], ["StudentA", "First", "A"], ["studenta", "Second", "B"]]
        response = self.client.post(self.url, {"users": rows})
        self.assertFailed(response, "Duplicate usernames in import")
        self.regular_user.userprofile.refresh_from_db()
        self.assertEqual(self.regular_user.userprofile.school, before_school)
        self.assertEqual(User.objects.count(), 2)
        self.assertFalse(UserCredentialExport.objects.exists())

    def test_import_rejects_ambiguous_historical_accounts_even_on_receipt_replay(self):
        data = {"users": [["student", "New", "A"]]}
        first = self.client.post(self.url, data)
        self.assertSuccess(first)
        self.create_user(username="STUDENT", password="legacy-pass", login=False)
        original_passwords = dict(User.objects.filter(username__iexact="student").values_list("id", "password"))
        response = self.client.post(self.url, data)
        self.assertFailed(response, "Multiple existing accounts match the same login; no users were changed")
        self.assertEqual(dict(User.objects.filter(username__iexact="student").values_list("id", "password")), original_passwords)
        self.assertEqual(UserCredentialExport.objects.count(), 1)

    def test_mixed_import_only_updates_existing_classroom(self):
        profile = self.regular_user.userprofile
        profile.real_name, profile.school, profile.language = "Original Name", "Old Class", "en-US"
        profile.save()
        password_hash = self.regular_user.password
        data = {"users": [[self.username, "Do Not Replace", "New Class"], ["new_student", "New Name", "Class B"]]}
        response = self.client.post(self.url, data)
        self.assertSuccess(response)
        download = self.client.get(self.reverse("generate_user_api"), {"file_id": response.data["data"]["file_id"]})
        passwords = workbook_credentials(download.content)
        self.assertEqual(list(passwords), ["new_student"])
        self.regular_user.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual((profile.real_name, profile.school, profile.language), ("Original Name", "New Class", "en-US"))
        self.assertEqual(self.regular_user.password, password_hash)
        newcomer = User.objects.get(username="new_student")
        self.assertTrue(newcomer.check_password(passwords["new_student"]))
        self.assertEqual((newcomer.userprofile.real_name, newcomer.userprofile.school, newcomer.userprofile.language),
                         ("New Name", "Class B", "zh-CN"))

    def test_import_late_invalid_row_keeps_existing_profile(self):
        profile = self.regular_user.userprofile
        profile.school = "Old Class"
        profile.save()
        data = {"users": [[self.username, "Unchanged", "New Class"], ["invalid_student", "Missing Class"]]}
        self.assertFailed(self.client.post(self.url, data))
        profile.refresh_from_db()
        self.assertEqual(profile.school, "Old Class")
        self.assertEqual(User.objects.count(), 2)

    def test_import_duplicate_new_user_rolls_back_existing_update(self):
        profile = self.regular_user.userprofile
        profile.school = "Old Class"
        profile.save()
        data = {"users": [[self.username, "Unchanged", "New Class"],
                          ["duplicate_student", "New Name", "Class B"], ["duplicate_student", "Other Name", "Class C"]]}
        self.assertFailed(self.client.post(self.url, data))
        profile.refresh_from_db()
        self.assertEqual(profile.school, "Old Class")
        self.assertEqual(User.objects.count(), 2)

    def test_import_download_and_login(self):
        response = self.client.post(self.url, {"users": [["new_student", "Student", "A"]]})
        self.assertSuccess(response)
        download = self.client.get(self.reverse("generate_user_api"), {"file_id": response.data["data"]["file_id"]})
        self.assertEqual(download["Cache-Control"], "no-store, private")
        password = workbook_credentials(download.content)["new_student"]
        self.client.logout()
        self.assertSuccess(self.client.post(self.reverse("user_login_api"), {"username": "new_student", "password": password}))
        self.assertEqual(auth.get_user(self.client).username, "new_student")

    def test_import_response_loss_and_download_retry_preserve_credentials(self):
        data = {"users": [["new_student", "Student", "A"]]}
        first = self.client.post(self.url, data)
        file_id = first.data["data"]["file_id"]
        download_url = self.reverse("generate_user_api")
        before = User.objects.get(username="new_student").password
        content = self.client.get(download_url, {"file_id": file_id}).content
        with mock.patch("account.views.admin.secrets.token_urlsafe") as random_password:
            replay = self.client.post(self.url, data)
        random_password.assert_not_called()
        self.assertEqual(first.data, replay.data)
        self.assertEqual(self.client.get(download_url, {"file_id": file_id}).content, content)
        self.assertEqual(User.objects.get(username="new_student").password, before)
        self.assertEqual(UserCredentialExport.objects.count(), 1)
        self.assertEqual(self.client.get(download_url, {"list": 1}).data["data"][0]["file_id"], file_id)
        self.assertEqual(stat.S_IMODE(os.stat(self.export_directory).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(export_path(file_id)).st_mode), 0o600)

    def test_export_only_owner_super_admin_can_access(self):
        data = {"users": [["new_student", "Student", "A"]]}
        response = self.client.post(self.url, data)
        file_id = response.data["data"]["file_id"]
        download_url = self.reverse("generate_user_api")
        self.client.logout()
        for user in [None, self.regular_user, self.create_admin(login=False)]:
            if user:
                self.client.force_login(user)
            self.assertFailed(self.client.post(self.url, data))
            self.assertFailed(self.client.get(download_url, {"file_id": file_id}))
            self.assertFailed(self.client.get(download_url, {"list": 1}))
        self.create_super_admin(username="other_super")
        self.assertFailed(self.client.get(download_url, {"file_id": file_id}))
        self.assertEqual(self.client.get(download_url, {"list": 1}).data["data"], [])
        repeat = self.client.post(self.url, data)
        self.assertSuccess(repeat)
        self.assertIsNone(repeat.data["data"]["file_id"])
        self.client.force_login(self.user)
        self.user.is_disabled = True
        self.user.save(update_fields=["is_disabled"])
        self.assertFailed(self.client.get(download_url, {"file_id": file_id}))

    def test_export_failure_rolls_back_accounts_and_classroom(self):
        profile = self.regular_user.userprofile
        profile.school = "Original Class"
        profile.save()
        data = {"users": [[self.username, "Unchanged", "New Class"], ["new_student", "Student", "A"]]}
        for target, failure in [("account.credential_exports.os.fsync", OSError("disk full")),
                                ("account.credential_exports.UserCredentialExport.objects.create", IntegrityError("failed receipt"))]:
            with self.subTest(target=target), mock.patch(target, side_effect=failure):
                self.assertFailed(self.client.post(self.url, data))
            profile.refresh_from_db()
            self.assertEqual(profile.school, "Original Class")
            self.assertEqual(User.objects.count(), 2)
            self.assertFalse(UserCredentialExport.objects.exists())
            self.assertEqual(os.listdir(self.export_directory), [])

    def test_expired_exports_and_orphans_are_cleaned_without_reset(self):
        data = {"users": [["new_student", "Student", "A"]]}
        response = self.client.post(self.url, data)
        file_id = response.data["data"]["file_id"]
        path = export_path(file_id)
        before = User.objects.get(username="new_student").password
        UserCredentialExport.objects.filter(pk=file_id).update(expires_at=now() - timedelta(seconds=1))
        self.assertFailed(self.client.get(self.reverse("generate_user_api"), {"file_id": file_id}))
        self.assertFalse(os.path.exists(path))
        repeat = self.client.post(self.url, data)
        self.assertSuccess(repeat)
        self.assertIsNone(repeat.data["data"]["file_id"])
        self.assertEqual(User.objects.get(username="new_student").password, before)
        with open(path, "wb") as abandoned:
            abandoned.write(b"abandoned export")
        old_time = (now() - EXPORT_LIFETIME - timedelta(seconds=1)).timestamp()
        os.utime(path, (old_time, old_time))
        call_command("cleanup_user_credentials", stdout=io.StringIO())
        self.assertFalse(os.path.exists(path))

    def test_cleanup_does_not_remove_a_live_export_with_old_file_mtime(self):
        response = self.client.post(self.url, {"users": [["student", "New", "A"]]})
        file_id = response.data["data"]["file_id"]
        path = export_path(file_id)
        current_time = now()
        UserCredentialExport.objects.filter(pk=file_id).update(expires_at=current_time + timedelta(milliseconds=100))
        written_at = (current_time - EXPORT_LIFETIME - timedelta(milliseconds=100)).timestamp()
        os.utime(path, (written_at, written_at))
        with mock.patch("account.credential_exports.timezone.now", return_value=current_time):
            call_command("cleanup_user_credentials", stdout=io.StringIO())
            response = self.client.get(self.reverse("generate_user_api"), {"file_id": file_id})
        self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertTrue(os.path.exists(path))
        self.assertEqual(list(workbook_credentials(response.content)), ["student"])

    def test_export_rejects_path_traversal_and_loose_file_permissions(self):
        response = self.client.post(self.url, {"users": [["new_student", "Student", "A"]]})
        file_id = response.data["data"]["file_id"]
        download_url = self.reverse("generate_user_api")
        for bad_id in ["../../etc/passwd", file_id + "\n", "a" * 64]:
            self.assertFailed(self.client.get(download_url, {"file_id": bad_id}))
        os.chmod(export_path(file_id), 0o644)
        self.assertFailed(self.client.get(download_url, {"file_id": file_id}))

    def test_delete_users(self):
        self.test_import_users()
        user_ids = User.objects.filter(username__in=["user1", "user2"]).values_list("id", flat=True)
        user_ids = ",".join([str(id) for id in user_ids])
        resp = self.client.delete(self.url + "?id=" + user_ids)
        self.assertSuccess(resp)
        self.assertEqual(User.objects.all().count(), 2)


class GenerateUserAPITest(APITestCase):
    def setUp(self):
        self.export_directory = credential_test_directory(self)
        self.create_super_admin()
        self.url = self.reverse("generate_user_api")
        self.data = {
            "number_from": 100, "number_to": 105,
            "prefix": "pre", "suffix": "suf",
            "default_email": "test@test.com",
            "password_length": 8
        }

    def test_error_case(self):
        data = deepcopy(self.data)
        data["prefix"] = "t" * 16
        data["suffix"] = "s" * 14
        resp = self.client.post(self.url, data=data)
        self.assertEqual(resp.data["data"], "Username should not more than 32 characters")

        data2 = deepcopy(self.data)
        data2["number_from"] = 106
        resp = self.client.post(self.url, data=data2)
        self.assertEqual(resp.data["data"], "Start number must be lower than end number")

    def test_generate_user_success(self):
        resp = self.client.post(self.url, data=self.data)
        self.assertSuccess(resp)
        download = self.client.get(self.url, {"file_id": resp.data["data"]["file_id"]})
        credentials = workbook_credentials(download.content)
        self.assertEqual(len(credentials), 6)
        for username, password in credentials.items():
            self.assertTrue(User.objects.get(username=username).check_password(password))
        retry = self.client.post(self.url, data=self.data)
        self.assertEqual(retry.data, resp.data)
        self.assertEqual(User.objects.count(), 7)

    def test_generate_user_rejects_short_passwords(self):
        self.data["password_length"] = 0
        self.assertFailed(self.client.post(self.url, self.data))
        self.assertEqual(User.objects.count(), 1)

    def test_generate_normalizes_prefix_suffix_and_replays_case_variants(self):
        data = dict(self.data, prefix="Student", suffix="X", number_from=1, number_to=1)
        response = self.client.post(self.url, data)
        self.assertSuccess(response)
        replay = self.client.post(self.url, dict(data, prefix="student", suffix="x"))
        self.assertEqual(replay.data, response.data)
        download = self.client.get(self.url, {"file_id": response.data["data"]["file_id"]})
        credentials = workbook_credentials(download.content)
        self.assertEqual(list(credentials), ["student1x"])
        self.client.logout()
        self.assertSuccess(self.client.post(self.reverse("user_login_api"), {"username": "STUDENT1X", "password": credentials["student1x"]}))

    def test_generate_rejects_existing_mixed_case_and_ambiguous_history(self):
        data = dict(self.data, prefix="student", suffix="", number_from=1, number_to=2)
        existing = self.create_user(username="Student1", password="legacy-pass", login=False)
        original_password = existing.password
        self.assertFailed(self.client.post(self.url, data), "Username already exists; no users were created")
        self.assertFalse(User.objects.filter(username="student2").exists())
        self.create_user(username="STUDENT1", password="legacy-pass", login=False)
        self.assertFailed(self.client.post(self.url, data), "Multiple existing accounts match the same login; no users were changed")
        existing.refresh_from_db()
        self.assertEqual(existing.password, original_password)
        self.assertFalse(UserCredentialExport.objects.exists())


class OpenAPIAppkeyAPITest(APITestCase):
    def setUp(self):
        self.user = self.create_super_admin()
        self.url = self.reverse("open_api_appkey_api")

    def test_reset_appkey(self):
        resp = self.client.post(self.url, data={})
        self.assertFailed(resp)

        self.user.open_api = True
        self.user.save()
        resp = self.client.post(self.url, data={})
        self.assertSuccess(resp)
        self.assertEqual(resp.data["data"]["appkey"], User.objects.get(username=self.user.username).open_api_appkey)


class CredentialExportConcurrencyTest(TransactionTestCase):
    def test_different_admins_import_case_variants_without_duplicate_logins(self):
        self._different_admins_same_name(generate=False)

    def test_different_admins_generate_case_variants_without_duplicate_logins(self):
        self._different_admins_same_name(generate=True)

    def _different_admins_same_name(self, generate):
        credential_test_directory(self)
        owners = [User.objects.create(username="owner" + str(index), admin_type=AdminType.SUPER_ADMIN) for index in range(2)]
        UserProfile.objects.bulk_create([UserProfile(user=owner) for owner in owners])
        barrier = Barrier(2)

        def create_accounts(item):
            index, owner = item
            close_old_connections()
            try:
                client = APIClient()
                client.force_login(User.objects.get(pk=owner.pk))
                prefix = "STUDENT" if index else "student"
                if generate:
                    url, data = reverse("generate_user_api"), {"prefix": prefix, "suffix": "", "number_from": 1,
                                                               "number_to": 1, "password_length": 16}
                else:
                    url, data = reverse("user_admin_api"), {"users": [[prefix + "1", "Student", "A"]]}
                barrier.wait(timeout=10)
                return client.post(url, data, format="json").data
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(create_accounts, enumerate(owners)))
        self.assertEqual(User.objects.filter(username__iexact="student1").count(), 1)
        self.assertEqual(UserCredentialExport.objects.count(), 1)
        if generate:
            self.assertEqual(sum(response["error"] is None for response in responses), 1)
            self.assertIn("Username already exists; no users were created", [response["data"] for response in responses if response["error"]])
        else:
            self.assertTrue(all(response["error"] is None for response in responses))
            self.assertEqual(sorted(response["data"]["created_count"] for response in responses), [0, 1])
        receipt = UserCredentialExport.objects.get()
        with open(export_path(receipt.pk), "rb") as source:
            credentials = workbook_credentials(source.read())
        self.assertTrue(User.objects.get(username="student1").check_password(credentials["student1"]))

    def test_concurrent_import_retries_create_one_receipt_and_one_user(self):
        credential_test_directory(self)
        owner = User.objects.create(username="export_owner", admin_type=AdminType.SUPER_ADMIN)
        UserProfile.objects.create(user=owner)
        barrier = Barrier(2)

        def import_users():
            close_old_connections()
            try:
                client = APIClient()
                client.force_login(User.objects.get(pk=owner.pk))
                barrier.wait(timeout=10)
                return client.post(reverse("user_admin_api"), {"users": [["student", "Student", "A"]]}, format="json").data
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: import_users(), range(2)))
        self.assertIsNone(responses[0]["error"])
        self.assertEqual(responses[0], responses[1])
        self.assertEqual(User.objects.filter(username="student").count(), 1)
        self.assertEqual(UserCredentialExport.objects.count(), 1)

    def test_concurrent_admin_and_super_admin_cannot_share_download_permission(self):
        self._concurrent_export_permissions(other_role=AdminType.ADMIN, disabled=False)

    def test_concurrent_disabled_and_active_super_admin_keep_separate_permissions(self):
        self._concurrent_export_permissions(other_role=AdminType.SUPER_ADMIN, disabled=True)

    def _concurrent_export_permissions(self, other_role, disabled):
        credential_test_directory(self)
        owner = User.objects.create(username="allowed_owner", admin_type=AdminType.SUPER_ADMIN)
        denied = User.objects.create(username="denied_user", admin_type=other_role, is_disabled=disabled)
        UserProfile.objects.bulk_create([UserProfile(user=owner), UserProfile(user=denied)])
        barrier = Barrier(2)
        original = super_admin_required.check_permission

        def simultaneous_check(decorator, *args):
            # Both requests have reached the SAME decorator before either checks its user.
            if not disabled:
                barrier.wait(timeout=10)
            return original(decorator, *args)

        def read_exports(user):
            close_old_connections()
            try:
                client = APIClient()
                client.force_login(user)
                session = client.session
                session_key = session.session_key
                # Disabled sessions are rejected by middleware before the decorator.
                if disabled:
                    barrier.wait(timeout=10)
                response = client.get(reverse("generate_user_api"), {"list": 1})
                if disabled and user.pk == denied.pk:
                    self.assertNotIn(auth.SESSION_KEY, client.session)
                    self.assertFalse(session.exists(session_key))
                return response.data
            finally:
                connections.close_all()

        with mock.patch.object(super_admin_required, "check_permission", simultaneous_check):
            with ThreadPoolExecutor(max_workers=2) as pool:
                allowed, forbidden = list(pool.map(read_exports, [owner, denied]))
        self.assertIsNone(allowed["error"])
        self.assertEqual(forbidden["error"], "login-required" if disabled else "permission-denied")

import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, override_settings

from account.models import AdminType, ProblemPermission
from utils.api import APIError
from utils.api.tests import APITestCase

from .models import Problem, ProblemTag
from .views.admin import TestCaseZipProcessor


def testcase_zip(entries=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in (entries or {"1.in": b"1\r\n", "1.out": b"2\r\n"}).items():
            archive.writestr(name, content)
    stream.seek(0)
    return stream


def problem_zip(count=1, invalid_index=None, tags=None):
    entries = {}
    for index in range(1, count + 1):
        value = {
            "display_id": "LEGACY-" + str(index), "title": "Legacy import",
            "description": {"format": "html", "value": "Statement"},
            "input_description": {"format": "html", "value": "Input"},
            "output_description": {"format": "html", "value": "Output"},
            "hint": {"format": "html", "value": ""},
            "test_case_score": [{"score": 100, "input_name": "1.in", "output_name": "1.out"}],
            "time_limit": 1000, "memory_limit": 128, "samples": [{"input": "1", "output": "2"}],
            "template": {}, "spj": None, "rule_type": "ACM", "source": "", "answers": [],
            "tags": ["test"] if tags is None else tags,
        }
        if index == invalid_index:
            value.pop("title")
        entries[f"{index}/problem.json"] = json.dumps(value).encode()
        entries[f"{index}/testcase/1.in"] = b"1\n"
        entries[f"{index}/testcase/1.out"] = b"2\n"
    return testcase_zip(entries).getvalue()


def fps_xml(invalid_second=False):
    item = ("<item><title>FPS import</title><description>Statement</description><input>Input</input>"
            "<output>Output</output><time_limit unit='ms'>1000</time_limit>"
            "<memory_limit unit='MB'>128</memory_limit><sample_input>1</sample_input>"
            "<sample_output>2</sample_output><test_input>1</test_input><test_output>2</test_output>"
            "<img><src>sample.png</src><base64>cGljdHVyZQ==</base64></img></item>")
    second = item.replace("<title>FPS import</title>", "<title>" + "x" * 129 + "</title>")
    return ("<fps version='1.2'>" + item + (second if invalid_second else "") + "</fps>").encode()


class LegacyImportSecurityTests(APITestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.testcases = Path(self.temp.name, "testcases")
        self.uploads = Path(self.temp.name, "uploads")
        self.testcases.mkdir()
        self.uploads.mkdir()
        self.override = override_settings(TEST_CASE_DIR=str(self.testcases), UPLOAD_DIR=str(self.uploads))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.admin = self.create_admin()
        ProblemTag.objects.create(name="test", normalized_name="test")
        self.routes = ("/api/admin/test_case", "/api/admin/import_problem", "/api/admin/import_fps")

    def upload(self, route, content, client=None, **kwargs):
        data = {"file": SimpleUploadedFile("fixture.zip", content), "spj": "false"}
        if client:
            return client.post(route, data, **kwargs)
        return self.client.post(route, data, format="multipart", **kwargs)

    def test_none_permission_and_disabled_admin_cannot_upload(self):
        none = self.create_user("none", "password", admin_type=AdminType.ADMIN,
                                problem_permission=ProblemPermission.NONE, login=False)
        for user in (none, self.admin):
            self.client.force_login(user)
            if user == self.admin:
                user.is_disabled = True
                user.save(update_fields=["is_disabled"])
            for route in self.routes:
                with self.subTest(user=user.username, route=route):
                    response = self.client.post(route, {}, format="multipart")
                    self.assertIsNotNone(response.json()["error"])
                    self.assertNotEqual(response.json()["data"], "Upload failed")
                    self.assertNotEqual(response.json()["data"], "Parse upload file error")
        self.assertFalse(Problem.objects.exists())
        self.assertEqual(list(self.testcases.iterdir()), [])

    def test_upload_requires_csrf_and_all_three_token_uploads_succeed(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        payloads = (testcase_zip().getvalue(), problem_zip(), fps_xml())
        for route, content in zip(self.routes, payloads):
            with self.subTest(route=route):
                self.assertEqual(self.upload(route, content, client).status_code, 403)
                token = "c" * 32
                client.cookies["csrftoken"] = token
                response = self.upload(route, content, client, HTTP_X_CSRFTOKEN=token)
                self.assertIsNone(response.json()["error"], response.content)
        self.assertEqual(Problem.objects.count(), 2)

    def test_later_invalid_zip_problem_rolls_back_database_and_testcases(self):
        sentinel = self.testcases / "existing"
        sentinel.mkdir()
        (sentinel / "keep").write_text("existing data")
        response = self.upload("/api/admin/import_problem", problem_zip(count=2, invalid_index=2))
        self.assertFailed(response)
        self.assertFalse(Problem.objects.exists())
        self.assertEqual(list(self.testcases.iterdir()), [sentinel])
        self.assertEqual((sentinel / "keep").read_text(), "existing data")

    def test_invalid_tags_roll_back_created_problem_and_files(self):
        response = self.upload("/api/admin/import_problem", problem_zip(tags=["missing"]))
        self.assertFailed(response)
        self.assertFalse(Problem.objects.exists())
        self.assertEqual(list(self.testcases.iterdir()), [])

    def test_later_invalid_fps_problem_cleans_database_testcases_and_images(self):
        response = self.upload("/api/admin/import_fps", fps_xml(invalid_second=True))
        self.assertFailed(response)
        self.assertFalse(Problem.objects.exists())
        self.assertEqual(list(self.testcases.iterdir()), [])
        self.assertEqual(list(self.uploads.iterdir()), [])


class LegacyZipBoundsTests(SimpleTestCase):
    def test_size_and_compression_limits_reject_before_extracting(self):
        api = TestCaseZipProcessor()
        with tempfile.TemporaryDirectory() as directory, override_settings(TEST_CASE_DIR=directory):
            stream = testcase_zip({"1.in": b"x" * 100, "1.out": b"y"})
            with patch("problem.views.admin.FILE_LIMIT", 64), self.assertRaises(APIError):
                api.process_zip(stream, False)
            stream.seek(0)
            with patch("problem.views.admin.COMMAND_LIMIT", 64), self.assertRaises(APIError):
                api.process_zip(stream, False)
            with self.assertRaises(APIError):
                api.process_zip(testcase_zip({"1.in": b"x" * (2 * 1024 * 1024), "1.out": b"y"}), False)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_invalid_path_and_mid_write_failure_leave_no_directory(self):
        api = TestCaseZipProcessor()
        with tempfile.TemporaryDirectory() as directory, override_settings(TEST_CASE_DIR=directory):
            with self.assertRaises(APIError):
                api.process_zip(testcase_zip({"../1.in": b"x", "1.out": b"y"}), False)
            with patch.object(api, "read_member", side_effect=[b"1\n", OSError("disk error")]), \
                    self.assertRaises(OSError):
                api.process_zip(testcase_zip(), False)
            self.assertEqual(list(Path(directory).iterdir()), [])

import io
import json
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import dramatiq
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from account.tasks import send_email_async
from conf.views import TestCasePruneAPI
from utils.api import APIError, APIView
from utils.api.tests import APITestCase
from utils.cache import cache
from utils.shortcuts import send_email
from utils.throttling import TokenBucket
from submission.views.oj import SubmissionListAPI


class LegacyBoundaryTests(SimpleTestCase):
    @patch("submission.views.oj.Submission.objects.filter", side_effect=RuntimeError("synthetic-query-secret"))
    def test_submission_failure_is_an_error_without_raw_query_logging(self, queryset):
        request = RequestFactory().get("/api/submissions", {"limit": "10", "username": "synthetic-private-query"})
        request.user = AnonymousUser()
        with self.assertLogs("submission.views.oj", level="ERROR") as logs:
            response = SubmissionListAPI.as_view()(request)
        self.assertEqual(response.data["error"], "server-error")
        self.assertNotIn("synthetic-", "".join(logs.output) + response.content.decode())

    def test_non_object_and_malformed_json_never_reach_handler(self):
        class EchoView(APIView):
            def post(self, request):
                return self.success(request.data.get("value"))

        for body in ("null", "[]", '"string"', "0", "{", b"\xff"):
            with self.subTest(body=body):
                request = RequestFactory().post("/probe", data=body, content_type="application/json")
                self.assertEqual(EchoView.as_view()(request).data["error"], "invalid-request")

    def test_unexpected_exception_does_not_leak_into_logs(self):
        class FailureView(APIView):
            def get(self, request):
                raise RuntimeError("synthetic-secret-token-private-code")

        with self.assertLogs(level="ERROR") as logs:
            response = FailureView.as_view()(RequestFactory().get("/probe"))
        self.assertEqual(response.data["error"], "server-error")
        self.assertIn("RuntimeError", "".join(logs.output))
        self.assertNotIn("synthetic-secret", "".join(logs.output) + response.content.decode())

    def test_prune_rejects_escape_symlink_and_referenced_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = root / "cases"
            cases.mkdir()
            outside = root / "outside"
            outside.mkdir()
            sentinel = outside / "keep"
            sentinel.write_text("test")
            valid_id = "a" * 32
            (cases / valid_id).symlink_to(outside, target_is_directory=True)
            with override_settings(TEST_CASE_DIR=str(cases)), patch("conf.views.Problem.objects.filter") as query:
                query.return_value.exists.return_value = False
                for value in ("../outside", str(outside), "", None, valid_id):
                    with self.subTest(value=value), self.assertRaises(APIError):
                        TestCasePruneAPI.delete_one(value)
                (cases / valid_id).unlink()
                (cases / valid_id).mkdir()
                query.return_value.exists.return_value = True
                with self.assertRaisesRegex(APIError, "still in use"):
                    TestCasePruneAPI.delete_one(valid_id)
                self.assertTrue((cases / valid_id).exists())
                query.return_value.exists.return_value = False
                TestCasePruneAPI.delete_one(valid_id)
                TestCasePruneAPI.delete_one(valid_id)
                self.assertFalse((cases / valid_id).exists())
            self.assertTrue(sentinel.exists())

    @patch("utils.shortcuts.Envelope")
    def test_smtp_has_finite_timeout(self, envelope):
        send_email({"email": "sender@example.invalid", "password": "secret", "server": "smtp.invalid", "port": 25, "tls": False},
                   "sender", "recipient@example.invalid", "recipient", "test", "test")
        self.assertEqual(envelope.return_value.send.call_args.kwargs["timeout"], 10)

    @patch("account.tasks.SysOptions")
    @patch("account.tasks.send_email", side_effect=TimeoutError("synthetic-smtp-secret"))
    def test_smtp_failure_remains_retryable_and_sanitized(self, sender, options):
        options.smtp_config = {"server": "smtp.invalid"}
        with self.assertLogs("account.tasks", level="ERROR") as logs:
            with self.assertRaises(dramatiq.Retry) as caught:
                send_email_async.fn("sender", "recipient@example.invalid", "name", "subject", "content")
        self.assertNotIn("synthetic-smtp-secret", "".join(logs.output) + str(caught.exception))


class AtomicThrottleTests(SimpleTestCase):
    def test_concurrent_requests_cannot_spend_one_token_twice(self):
        key = "acceptance-throttle:" + uuid.uuid4().hex
        self.addCleanup(cache.delete, key)
        barrier = threading.Barrier(8)

        def consume(_):
            barrier.wait(timeout=5)
            return TokenBucket(key, 1, 0.001, 1, cache).consume()

        with ThreadPoolExecutor(max_workers=8) as pool:
            result = list(pool.map(consume, range(8)))
        self.assertEqual(sum(allowed for allowed, _ in result), 1)
        self.assertTrue(all(wait > 0 for allowed, wait in result if not allowed))
        self.assertGreater(cache.ttl(key), 0)

    def test_refill_and_incomplete_legacy_state_are_recoverable(self):
        key = "acceptance-throttle:" + uuid.uuid4().hex
        self.addCleanup(cache.delete, key)
        cache.hset(key, "last_capacity", 0)
        self.assertFalse(TokenBucket(key, 1, 1, 1, cache).consume()[0])
        cache.hset(key, "last_timestamp", 1)
        self.assertTrue(TokenBucket(key, 1, 1, 1, cache).consume()[0])


class RichTextUploadTests(APITestCase):
    def setUp(self):
        self.create_admin()
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.login(username="admin", password="admin")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = override_settings(UPLOAD_DIR=self.temp.name)
        self.directory.enable()
        self.addCleanup(self.directory.disable)

    def test_upload_requires_csrf_and_image_content(self):
        for url, key in (("/api/admin/upload_file", "file"), ("/api/admin/upload_image/", "image")):
            response = self.client.post(url, {key: SimpleUploadedFile("image.png", b"<html>not an image</html>")}, format="multipart")
            self.assertEqual(response.status_code, 403)
        token = "a" * 32
        self.client.cookies["csrftoken"] = token
        response = self.client.post("/api/admin/upload_image/", {"image": SimpleUploadedFile("image.png", b"<html>not an image</html>")},
                                    format="multipart", HTTP_X_CSRFTOKEN=token)
        self.assertFalse(json.loads(response.content)["success"])
        image = io.BytesIO()
        Image.new("RGB", (1, 1)).save(image, format="PNG")
        response = self.client.post("/api/admin/upload_image/", {"image": SimpleUploadedFile("image.png", image.getvalue())},
                                    format="multipart", HTTP_X_CSRFTOKEN=token)
        self.assertTrue(json.loads(response.content)["success"])
        self.assertEqual(len(list(Path(self.temp.name).iterdir())), 1)

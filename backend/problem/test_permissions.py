import io
import os
import shutil
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.db import close_old_connections, connections
from django.test import SimpleTestCase, TransactionTestCase
from django.urls import reverse

from account.models import AdminType, ProblemPermission, User, UserProfile
from contest.models import Contest
from contest.tests import DEFAULT_CONTEST_DATA
from utils.api.tests import APIClient

from .models import Problem
from .tests import DEFAULT_PROBLEM_DATA, ProblemCreateTestBase
from .utils import clone_test_case
from .views.oj import DLTestCaseZipProcessor


class ProblemCopyPermissionTest(ProblemCreateTestBase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(TEST_CASE_DIR=directory.name)
        override.enable()
        self.addCleanup(override.disable)
        self.owner = self.create_admin("owner", "owner-password", login=False)
        self.other = self.create_admin("other", "other-password")
        data = dict(deepcopy(DEFAULT_CONTEST_DATA), password="")
        self.foreign_contest = Contest.objects.create(created_by=self.owner, **data)
        self.own_contest = Contest.objects.create(created_by=self.other, **data)
        self.problem = self.add_problem(DEFAULT_PROBLEM_DATA, self.owner)
        self.ensure_test_case_dir(self.problem.test_case_id, allow_public_download=True)
        self.add_url = self.reverse("add_contest_problem_from_public_api")

    def test_cannot_insert_into_foreign_contest(self):
        response = self.client.post(self.add_url, {"contest_id": self.foreign_contest.id,
                                                   "problem_id": self.problem.id, "display_id": "copy"})
        self.assertFailed(response)
        self.assertFalse(Problem.objects.filter(contest=self.foreign_contest).exists())

    def test_cannot_copy_foreign_private_or_contest_problem(self):
        self.problem.visible = False
        self.problem.save(update_fields=["visible"])
        for source_contest in (None, self.foreign_contest):
            with self.subTest(contest=source_contest):
                self.problem.contest = source_contest
                self.problem.save(update_fields=["contest"])
                response = self.client.post(self.add_url, {"contest_id": self.own_contest.id,
                                                           "problem_id": self.problem.id, "display_id": "copy"})
                self.assertFailed(response)
                self.assertFalse(Problem.objects.filter(contest=self.own_contest).exists())

    def test_can_copy_public_problem_into_own_contest(self):
        response = self.client.post(self.add_url, {"contest_id": self.own_contest.id,
                                                   "problem_id": self.problem.id, "display_id": "copy"})
        self.assertSuccess(response)
        self.assertTrue(Problem.objects.filter(contest=self.own_contest, _id="copy").exists())

    def test_cannot_publish_foreign_contest_problem(self):
        self.problem.contest = self.foreign_contest
        self.problem.save(update_fields=["contest"])
        response = self.client.post(self.reverse("make_public_api"), {"id": self.problem.id, "display_id": "copy"})
        self.assertFailed(response)
        self.problem.refresh_from_db()
        self.assertFalse(self.problem.is_public)
        self.assertFalse(Problem.objects.filter(_id="copy").exists())

    def test_admin_without_problem_permission_cannot_copy_or_publish(self):
        self.other.problem_permission = ProblemPermission.NONE
        self.other.save(update_fields=["problem_permission"])
        response = self.client.post(self.add_url, {"contest_id": self.own_contest.id,
                                                   "problem_id": self.problem.id, "display_id": "copy"})
        self.assertFailed(response)
        self.problem.contest = self.own_contest
        self.problem.save(update_fields=["contest"])
        self.assertFailed(self.client.post(self.reverse("make_public_api"), {
            "id": self.problem.id, "display_id": "copy"}))
        self.assertFalse(Problem.objects.filter(_id="copy").exists())

    def test_missing_test_cases_do_not_mark_source_as_public(self):
        self.problem.contest = self.own_contest
        self.problem.save(update_fields=["contest"])
        shutil.rmtree(os.path.join(settings.TEST_CASE_DIR, self.problem.test_case_id))
        self.assertFailed(self.client.post(self.reverse("make_public_api"), {
            "id": self.problem.id, "display_id": "copy"}))
        self.problem.refresh_from_db()
        self.assertFalse(self.problem.is_public)
        self.assertFalse(Problem.objects.filter(_id="copy").exists())

    def test_copy_failure_rolls_back_rows_flags_and_new_files(self):
        self.problem.contest = self.own_contest
        self.problem.save(update_fields=["contest"])
        original_directories = set(os.listdir(settings.TEST_CASE_DIR))
        requests = [(self.add_url, {"contest_id": self.own_contest.id,
                                    "problem_id": self.problem.id, "display_id": "copy"}),
                    (self.reverse("make_public_api"), {"id": self.problem.id, "display_id": "copy"})]
        for url, payload in requests:
            with self.subTest(url=url):
                with mock.patch.object(type(self.problem.tags), "set", side_effect=RuntimeError("tag write failed")):
                    self.assertFailed(self.client.post(url, payload))
                self.problem.refresh_from_db()
                self.assertFalse(self.problem.is_public)
                self.assertFalse(Problem.objects.filter(_id="copy").exists())
                self.assertEqual(set(os.listdir(settings.TEST_CASE_DIR)), original_directories)

    def test_hidden_contest_denies_public_test_case_download(self):
        self.problem.contest = self.foreign_contest
        self.problem.save(update_fields=["contest"])
        self.foreign_contest.visible = False
        self.foreign_contest.save(update_fields=["visible"])
        response = self.client.get(self.reverse("dl_test_case_api"), {"problem_id": self.problem.id})
        self.assertFailed(response)


class ProblemCopyConcurrencyTest(TransactionTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(TEST_CASE_DIR=directory.name)
        override.enable()
        self.addCleanup(override.disable)
        self.owner = User.objects.create(username="copy-owner", admin_type=AdminType.ADMIN,
                                         problem_permission=ProblemPermission.OWN)
        UserProfile.objects.create(user=self.owner)
        self.contest = Contest.objects.create(created_by=self.owner, **deepcopy(DEFAULT_CONTEST_DATA))
        self.problem = ProblemCreateTestBase.add_problem(DEFAULT_PROBLEM_DATA, self.owner)
        ProblemCreateTestBase.ensure_test_case_dir(self.problem.test_case_id)

    def _concurrent_requests(self, url, payload):
        barrier = Barrier(2)

        def request_copy(_):
            close_old_connections()
            try:
                client = APIClient()
                client.force_login(User.objects.get(pk=self.owner.pk))
                barrier.wait(timeout=10)
                return client.post(url, payload, format="json").data
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(request_copy, range(2)))
        self.assertEqual(sum(response["error"] is None for response in responses), 1)
        self.assertFalse(any(response["error"] == "server-error" for response in responses))
        self.assertEqual(Problem.objects.filter(_id="copy").count(), 1)
        self.assertEqual(len(os.listdir(settings.TEST_CASE_DIR)), 2)

    def test_repeated_contest_copy_creates_one_problem_and_directory(self):
        self._concurrent_requests(reverse("add_contest_problem_from_public_api"), {
            "contest_id": self.contest.id, "problem_id": self.problem.id, "display_id": "copy"})

    def test_repeated_publication_creates_one_problem_and_directory(self):
        self.problem.contest = self.contest
        self.problem.save(update_fields=["contest"])
        self._concurrent_requests(reverse("make_public_api"), {"id": self.problem.id, "display_id": "copy"})
        self.problem.refresh_from_db()
        self.assertTrue(self.problem.is_public)


class TestCaseCloneCleanupTest(SimpleTestCase):
    def test_failed_copy_only_removes_the_directory_it_created(self):
        with tempfile.TemporaryDirectory() as directory, self.settings(TEST_CASE_DIR=directory):
            os.mkdir(os.path.join(directory, "source"))
            with mock.patch("problem.utils.rand_str", return_value="new"), \
                    mock.patch("problem.utils.shutil.copytree", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    clone_test_case("source")
            self.assertEqual(os.listdir(directory), ["source"])

            os.mkdir(os.path.join(directory, "existing"))
            with mock.patch("problem.utils.rand_str", return_value="existing"):
                with self.assertRaises(FileExistsError):
                    clone_test_case("source")
            self.assertEqual(set(os.listdir(directory)), {"source", "existing"})


class TestCaseDownloadIsolationTest(SimpleTestCase):
    def test_overlapping_downloads_have_independent_archives_and_close_files(self):
        with tempfile.TemporaryDirectory() as directory, self.settings(TEST_CASE_DIR=directory):
            problem = SimpleNamespace(test_case_id="cases", spj=False, id=1)
            ProblemCreateTestBase.ensure_test_case_dir(problem.test_case_id)
            processor = DLTestCaseZipProcessor()
            first = processor.build_download_response(problem)
            first_file = first.file_to_stream
            second = None
            try:
                with open(os.path.join(directory, "cases", "1.in"), "w") as testcase:
                    testcase.write("updated input\n")
                second = processor.build_download_response(problem)
                second_file = second.file_to_stream
                with zipfile.ZipFile(io.BytesIO(b"".join(first.streaming_content))) as archive:
                    self.assertEqual(archive.read("1.in"), b"1\n")
                with zipfile.ZipFile(io.BytesIO(b"".join(second.streaming_content))) as archive:
                    self.assertEqual(archive.read("1.in"), b"updated input\n")
            finally:
                first.close()
                if second:
                    second.close()
            self.assertTrue(first_file.closed)
            self.assertTrue(second_file.closed)
            self.assertFalse(os.path.exists(os.path.join(directory, "cases", "cases.zip")))

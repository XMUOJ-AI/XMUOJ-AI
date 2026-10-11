import copy
import hashlib
import io
import json
import os
import stat
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import include, path

from account.models import AdminType, ProblemPermission, User
from knowledge.models import KnowledgeMappingBatch, ProblemKnowledge
from problem.models import Problem, ProblemTag
from utils.contract_api import ContractError

from .archive import content_hash, expected_problem, validator
from .models import ExternalProblemBinding, ExternalTagMapping, ProblemImportBatch
from .services import (commit_batch, receive_archive, recover_batches, report,
                       request_commit, validate_batch, worker_lock)

urlpatterns = [path("api/", include("problem_import.urls"))]
GOLDEN = Path(__file__).resolve().parents[2] / "docs" / "examples" / "problem-batch-example.zip"


def package(key="test-batch", count=1, mutate=None):
    with zipfile.ZipFile(GOLDEN) as source:
        files = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(files.pop("manifest.json"))
    manifest["batch_id"] = key
    template = json.loads(files["metadata/problems.jsonl"])
    records, entries = [], []
    for index in range(1, count + 1):
        record = copy.deepcopy(template)
        record["source_id"] = "P" + str(1000 + index)
        record["source_url"] = "https://www.luogu.com.cn/problem/" + record["source_id"]
        record["problem_key"] = "luogu_" + record["source_id"]
        record.pop("raw_data_path", None)
        records.append(record)
        entries.append(dict(manifest["problems"][0], directory=str(index), metadata_line=index,
                            problem_key=record["problem_key"]))
        files[f"{index}/problem.json"] = json.dumps(expected_problem(record, [
            {"score": 100, "input_name": "1.in", "output_name": "1.out"}]), ensure_ascii=False).encode()
        files[f"{index}/testcase/1.in"] = b"1 2\n"
        files[f"{index}/testcase/1.out"] = b"3\n"
    manifest.update(problem_count=count, importable_count=count, problems=entries)
    if mutate:
        mutate(records, entries, files)
    manifest["importable_count"] = sum(entry["directory"] is not None for entry in entries)
    files["metadata/problems.jsonl"] = b"".join(json.dumps(row, ensure_ascii=False).encode() + b"\n" for row in records)
    manifest["files"] = [{"path": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                          "media_type": "application/x-ndjson" if name.endswith(".jsonl") else
                          "application/json" if name.endswith(".json") else
                          "text/csv" if name.endswith(".csv") else "text/plain"}
                         for name, data in files.items()]
    files["manifest.json"] = json.dumps(manifest).encode()
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    target.seek(0)
    return target


@override_settings(ROOT_URLCONF="problem_import.tests")
class ImportTests(TransactionTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(PROBLEM_IMPORT_DIR=Path(self.temp.name) / "archive",
                                                   TEST_CASE_DIR=str(Path(self.temp.name) / "testcases"))
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.admin = User.objects.create(username="import-admin", admin_type=AdminType.SUPER_ADMIN)
        self.student = User.objects.create(username="import-student")
        self.tag = ProblemTag.objects.create(name="基本输入输出", normalized_name="基本输入输出")

    def validated(self, stream=None):
        batch, _ = receive_archive(stream or package(), self.admin)
        return validate_batch(batch.pk)

    def commit_data(self, batch, partial=False, ids=None):
        issues = batch.issues + [i for row in batch.problems.all() for i in row.validation_errors]
        return {"allow_partial": partial, "problem_ids": ids or [],
                "acknowledged_warning_codes": sorted({i["code"] for i in issues if i["level"] == "warning"})}

    def commit(self, batch, partial=False, key="commit", ids=None):
        batch, _, _ = request_commit(batch.batch_key, self.admin, key, self.commit_data(batch, partial, ids))
        return commit_batch(batch.pk)

    def test_golden_schema_hash_and_hidden_import(self):
        with GOLDEN.open("rb") as source:
            batch = self.validated(source)
        self.assertEqual(batch.status, "validated", batch.issues)
        self.assertEqual(batch.valid_count, 1)
        self.assertEqual(Problem.objects.count(), 0)
        self.assertFalse(Path(self.temp.name, "testcases").exists())
        batch = self.commit(batch)
        self.assertEqual(batch.status, "imported")
        problem = Problem.objects.get()
        self.assertFalse(problem.visible)
        self.assertEqual(problem._id, "LUOGU-P1001")
        self.assertEqual(list(problem.tags.all()), [self.tag])
        info = json.loads(Path(self.temp.name, "testcases", problem.test_case_id, "info").read_text())
        self.assertFalse(info["allow_public_test_case_download"])
        self.assertEqual(info["test_cases"]["1"]["stripped_output_md5"], hashlib.md5(b"3").hexdigest())
        self.assertEqual(ExternalProblemBinding.objects.count(), 1)
        self.assertEqual(ProblemKnowledge.objects.count(), 0)
        self.assertEqual(KnowledgeMappingBatch.objects.count(), 0)
        self.assertFalse(ExternalTagMapping.objects.exclude(status="pending", knowledge_point=None).exists())
        validator("problem-import-report-v1").validate(report(batch))

    def test_upload_dedup_batch_conflict_and_size_stream(self):
        batch, _ = receive_archive(package(), self.admin)
        again, created = receive_archive(package(), self.admin)
        self.assertFalse(created)
        self.assertEqual(batch.pk, again.pk)
        with self.assertRaisesRegex(ContractError, "IMPORT_BATCH_CONFLICT"):
            receive_archive(package(count=2), self.admin)
        with patch("problem_import.services.WEB_LIMIT", 20):
            with self.assertRaisesRegex(ContractError, "IMPORT_SIZE_LIMIT"):
                receive_archive(io.BytesIO(b"x" * 21), self.admin)
        self.assertEqual(len(list(Path(self.temp.name, "archive").iterdir())), 1)

    def test_warning_confirmation_and_idempotency(self):
        batch = self.validated()
        data = self.commit_data(batch)
        with self.assertRaisesRegex(ContractError, "IMPORT_WARNING_ACK_REQUIRED"):
            request_commit(batch.batch_key, self.admin, "missing-ack", dict(data, acknowledged_warning_codes=[]))
        batch, response, _ = request_commit(batch.batch_key, self.admin, "one", data)
        commit_batch(batch.pk)
        _, again, send = request_commit(batch.batch_key, self.admin, "one", data)
        self.assertEqual(response, again)
        self.assertFalse(send)
        with self.assertRaisesRegex(ContractError, "IMPORT_IDEMPOTENCY_CONFLICT"):
            request_commit(batch.batch_key, self.admin, "one", dict(data, allow_partial=True))
        commit_batch(batch.pk)
        self.assertEqual(Problem.objects.count(), 1)

    def test_cross_batch_source_idempotency_and_updated_source(self):
        self.commit(self.validated())
        duplicate = self.validated(package("second-batch"))
        self.assertEqual(duplicate.problems.get().import_status, "duplicate")
        self.commit(duplicate)
        self.assertEqual(Problem.objects.count(), 1)
        self.assertEqual(ExternalProblemBinding.objects.get().latest_collected_problem_id, duplicate.problems.get().pk)

        def update(records, entries, files):
            records[0]["title"] = records[0]["title_cn"] = "Changed"
            records[0]["content_hash"] = content_hash(records[0])
            value = json.loads(files["1/problem.json"])
            value["title"] = "Changed"
            files["1/problem.json"] = json.dumps(value).encode()

        changed = self.validated(package("changed-batch", mutate=update))
        self.assertEqual(changed.problems.get().import_status, "skipped")
        self.assertIn("IMPORT_SOURCE_UPDATED", [i["code"] for i in changed.problems.get().validation_errors])
        self.assertEqual(Problem.objects.get().title, "A+B 问题")

    def test_schema_unknown_field_and_content_hash_are_rejected(self):
        def mutate(records, entries, files):
            records[0]["unexpected"] = True
        batch = self.validated(package(mutate=mutate))
        self.assertEqual(batch.problems.get().import_status, "failed")
        with self.assertRaisesRegex(ContractError, "IMPORT_VALIDATION_FAILED"):
            self.commit(batch)
        bad_hash = self.validated(package(
            "bad-hash", mutate=lambda records, entries, files: records[0].update(content_hash="0" * 64)))
        self.assertIn("IMPORT_CONTENT_HASH_MISMATCH", [i["code"] for i in bad_hash.problems.get().validation_errors])

    def test_zip_slip_symlink_executable_and_bomb(self):
        for name, mode, data in (("../escape", 0o644, b"x"), ("/absolute", 0o644, b"x"),
                                 ("link", stat.S_IFLNK | 0o777, b"target"),
                                 ("execute", stat.S_IFREG | 0o755, b"x"),
                                 ("huge", 0o644, b"0" * (2 * 1024 * 1024))):
            with self.subTest(name=name):
                stream = package(name.replace("/", "-").replace(".", "-"))
                with zipfile.ZipFile(stream, "a", zipfile.ZIP_DEFLATED) as archive:
                    entry = zipfile.ZipInfo(name)
                    entry.external_attr = mode << 16
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(entry, data)
                stream.seek(0)
                with self.assertRaises(ContractError):
                    receive_archive(stream, self.admin)
        self.assertFalse(Path(self.temp.name, "escape").exists())

    def test_corrupt_file_and_duplicate_zip_path(self):
        stream = package()
        with zipfile.ZipFile(stream, "a") as archive:
            archive.writestr("not-declared.txt", b"x")
        stream.seek(0)
        batch = self.validated(stream)
        self.assertEqual(batch.status, "failed")
        self.assertEqual(batch.issues[0]["code"], "IMPORT_FILE_SET_MISMATCH")
        corrupt = package("corrupt")
        with zipfile.ZipFile(corrupt) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        files["1/testcase/1.out"] = b"7\n"
        rebuilt = io.BytesIO()
        with zipfile.ZipFile(rebuilt, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        rebuilt.seek(0)
        self.assertEqual(self.validated(rebuilt).issues[0]["code"], "IMPORT_FILE_HASH_MISMATCH")

    def test_atomic_failure_compensates_files_and_partial_retry(self):
        batch = self.validated(package(count=2))
        original = os.replace

        def fail_second(source, target):
            if Path(target).parent.joinpath(first_id).exists():
                raise OSError("injected filesystem error")
            return original(source, target)

        batch, _, _ = request_commit(batch.batch_key, self.admin, "atomic", self.commit_data(batch))
        first_id = batch.problems.first().allocated_test_case_id
        with patch("problem_import.services.os.replace", side_effect=fail_second):
            failed = commit_batch(batch.pk)
        self.assertEqual(failed.status, "failed")
        self.assertEqual(Problem.objects.count(), 0)
        self.assertEqual(ExternalProblemBinding.objects.count(), 0)
        self.assertEqual(list(Path(self.temp.name, "testcases").iterdir()), [])
        batch, _, _ = request_commit(batch.batch_key, self.admin, "partial", self.commit_data(failed, True))
        with patch("problem_import.services.os.replace", side_effect=fail_second):
            partial = commit_batch(batch.pk)
        self.assertEqual(partial.status, "partial")
        self.assertEqual(Problem.objects.count(), 1)
        complete = self.commit(partial, partial=True, key="retry")
        self.assertEqual(complete.status, "imported")
        self.assertEqual(Problem.objects.count(), 2)
        self.assertEqual(ExternalProblemBinding.objects.count(), 2)
        for row in complete.problems.all():
            self.assertTrue(any(i["level"] == "info" and i["code"] == "IMPORT_COMMIT_FAILED" for i in row.validation_errors))

    def test_recovery_cleans_only_allocated_unreferenced_directory(self):
        batch = self.validated()
        batch, _, _ = request_commit(batch.batch_key, self.admin, "crash", self.commit_data(batch))
        row = batch.problems.get()
        root = Path(self.temp.name, "testcases")
        (root / row.allocated_test_case_id).mkdir(parents=True)
        (root / "unrelated").mkdir()
        self.assertEqual(recover_batches(0), 1)
        self.assertFalse((root / row.allocated_test_case_id).exists())
        self.assertTrue((root / "unrelated").exists())
        row.refresh_from_db()
        self.assertEqual(row.import_error_code, "IMPORT_INTERRUPTED")
        self.assertEqual(self.commit(ProblemImportBatch.objects.get(pk=batch.pk), key="recover-retry").status, "imported")

    def test_parallel_commit_requests_and_duplicate_delivery(self):
        batch = self.validated()
        data = self.commit_data(batch)
        barrier = threading.Barrier(2)

        def request():
            close_old_connections()
            try:
                barrier.wait()
                return request_commit(batch.batch_key, self.admin, "parallel", data)[1]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(request) for _ in range(2)]
            self.assertEqual(futures[0].result(), futures[1].result())

        def run_worker():
            close_old_connections()
            try:
                barrier.wait()
                return commit_batch(batch.pk).status
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(run_worker) for _ in range(2)]
            for result in results:
                result.result()
        self.assertEqual(Problem.objects.count(), 1)

    def test_recovery_skips_active_worker_lock(self):
        batch = self.validated()
        request_commit(batch.batch_key, self.admin, "active", self.commit_data(batch))
        with worker_lock(batch.pk):
            def recover():
                close_old_connections()
                try:
                    return recover_batches(0)
                finally:
                    close_old_connections()
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(recover).result(), 0)

    def test_api_permissions_csrf_cursor_and_commit(self):
        base = "/api/admin/problem-import/batches"
        batch = self.validated(package(count=2))
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(base + "/" + batch.batch_key).status_code, 401)
        client.force_login(self.student)
        self.assertEqual(client.get(base + "/" + batch.batch_key).status_code, 403)
        # Import creates problems: an admin without problem permission is refused like legacy problem APIs.
        no_problem_admin = User.objects.create(username="import-admin-none", admin_type=AdminType.ADMIN,
                                               problem_permission=ProblemPermission.NONE)
        client.force_login(no_problem_admin)
        self.assertEqual(client.get(base + "/" + batch.batch_key).status_code, 403)
        client.force_login(self.admin)
        self.assertEqual(client.post(base, {"archive": package()}).status_code, 403)
        first = client.get(base + "/" + batch.batch_key + "/problems?limit=1")
        self.assertEqual(first.status_code, 200, first.content)
        cursor = first.json()["data"]["page"]["next_cursor"]
        second = client.get(base + "/" + batch.batch_key + "/problems", {"limit": 1, "cursor": cursor})
        self.assertNotEqual(first.json()["data"]["items"][0]["id"], second.json()["data"]["items"][0]["id"])
        self.assertEqual(client.get(base + "/" + batch.batch_key + "/errors", {"cursor": cursor}).status_code, 400)
        self.assertEqual(client.get(base + "/" + batch.batch_key + "/problems", {"cursor": "tampered"}).status_code, 400)
        self.assertEqual(first["X-API-Version"], "1.0.0")
        token = "a" * 32
        client.cookies["csrftoken"] = token
        with patch("problem_import.views.commit_import_batch.send"):
            response = client.post(base + "/" + batch.batch_key + "/commit", json.dumps(self.commit_data(batch)),
                                   content_type="application/json", HTTP_X_CSRFTOKEN=token, HTTP_IDEMPOTENCY_KEY="api")
        self.assertEqual(response.status_code, 202, response.content)

    def test_batch_scope_covers_detail_pages_cursor_and_commit(self):
        owner = User.objects.create(username="import-owner", admin_type=AdminType.ADMIN,
                                    problem_permission=ProblemPermission.OWN)
        other = User.objects.create(username="import-other", admin_type=AdminType.ADMIN,
                                    problem_permission=ProblemPermission.OWN)
        all_admin = User.objects.create(username="import-all", admin_type=AdminType.ADMIN,
                                        problem_permission=ProblemPermission.ALL)
        batch, _ = receive_archive(package(count=2), owner)
        batch = validate_batch(batch.pk)
        base = "/api/admin/problem-import/batches/" + batch.batch_key
        client = Client()
        client.force_login(owner)
        cursor = client.get(base + "/problems", {"limit": 1}).json()["data"]["page"]["next_cursor"]
        self.assertIsNotNone(cursor)
        client.force_login(other)
        missing = client.get("/api/admin/problem-import/batches/missing-batch").json()
        for suffix, query in (("", {}), ("/problems", {"cursor": cursor}),
                              ("/problems", {"cursor": "tampered"}), ("/errors", {"limit": 1})):
            with self.subTest(suffix=suffix, query=query):
                response = client.get(base + suffix, query)
                self.assertEqual(response.status_code, 404, response.content)
                self.assertEqual(response.json()["error"], missing["error"])
                self.assertEqual(response.json()["data"], missing["data"])
        data = self.commit_data(batch)
        with patch("problem_import.views.commit_import_batch.send") as send:
            for payload, headers in (({}, {}), (data, {"HTTP_IDEMPOTENCY_KEY": "stolen"})):
                response = client.post(base + "/commit", json.dumps(payload),
                                       content_type="application/json", **headers)
                self.assertEqual(response.status_code, 404, response.content)
            send.assert_not_called()
        with self.assertRaisesRegex(ContractError, "IMPORT_NOT_FOUND"):
            request_commit(batch.batch_key, other, "direct", data)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "validated")
        self.assertEqual(batch.commit_operations, {})
        self.assertFalse(batch.problems.exclude(allocated_test_case_id=None).exists())

        for index, actor in enumerate((owner, all_admin, self.admin)):
            client.force_login(actor)
            for suffix in ("", "/problems", "/errors"):
                self.assertEqual(client.get(base + suffix).status_code, 200)
            own_batch, _ = receive_archive(package("scope-commit-" + str(index)), owner)
            own_batch = validate_batch(own_batch.pk)
            endpoint = "/api/admin/problem-import/batches/" + own_batch.batch_key + "/commit"
            with patch("problem_import.views.commit_import_batch.send"):
                response = client.post(endpoint, json.dumps(self.commit_data(own_batch)),
                                       content_type="application/json", HTTP_IDEMPOTENCY_KEY="scope")
                self.assertEqual(response.status_code, 202, response.content)
                replay = client.post(endpoint, json.dumps(self.commit_data(own_batch)),
                                     content_type="application/json", HTTP_IDEMPOTENCY_KEY="scope")
                self.assertEqual(replay.status_code, 202, replay.content)
                self.assertEqual(response.json()["data"], replay.json()["data"])

    def test_upload_duplicate_does_not_disclose_another_owners_batch(self):
        owner = User.objects.create(username="upload-owner", admin_type=AdminType.ADMIN,
                                    problem_permission=ProblemPermission.OWN)
        other = User.objects.create(username="upload-other", admin_type=AdminType.ADMIN,
                                    problem_permission=ProblemPermission.OWN)
        all_admin = User.objects.create(username="upload-all", admin_type=AdminType.ADMIN,
                                        problem_permission=ProblemPermission.ALL)
        archive = package().getvalue()
        batch, _ = receive_archive(io.BytesIO(archive), owner)
        with self.assertRaisesRegex(ContractError, "IMPORT_BATCH_CONFLICT") as denied:
            receive_archive(io.BytesIO(archive), other)
        self.assertEqual(denied.exception.status, 409)
        self.assertEqual(denied.exception.details, {})
        client = Client()
        client.force_login(other)
        endpoint = "/api/admin/problem-import/batches"
        with patch("problem_import.views.validate_import_batch.send") as send:
            same_hash = client.post(endpoint, {"archive": io.BytesIO(archive)})
            same_key = client.post(endpoint, {"archive": package(count=2)})
            for response in (same_hash, same_key):
                self.assertEqual(response.status_code, 409, response.content)
                self.assertEqual(response.json()["error"], "IMPORT_BATCH_CONFLICT")
                self.assertEqual(response.json()["data"]["details"], {})
                self.assertNotIn("Location", response)
                self.assertNotIn(batch.batch_key, response.content.decode())
                self.assertNotIn(batch.archive_sha256, response.content.decode())
            self.assertEqual(same_hash.json()["data"], same_key.json()["data"])
            send.assert_not_called()
            for actor in (owner, all_admin, self.admin):
                client.force_login(actor)
                response = client.post(endpoint, {"archive": io.BytesIO(archive)})
                self.assertEqual(response.status_code, 202, response.content)
                self.assertEqual(response.json()["data"]["batch_id"], batch.batch_key)
        self.assertEqual(ProblemImportBatch.objects.count(), 1)
        batch.refresh_from_db()
        self.assertEqual(batch.uploaded_by_id, owner.pk)
        self.assertEqual(list(Path(self.temp.name, "archive").iterdir()), [Path(batch.archive_path)])

    def test_services_reject_users_without_import_permission(self):
        no_permission = User.objects.create(username="service-none", admin_type=AdminType.ADMIN)
        disabled = User.objects.create(username="service-disabled", admin_type=AdminType.SUPER_ADMIN,
                                       is_disabled=True)
        batch = self.validated()
        for actor in (self.student, no_permission, disabled):
            with self.subTest(actor=actor.username):
                with self.assertRaisesRegex(ContractError, "IMPORT_PERMISSION_DENIED"):
                    receive_archive(package(), actor)
                with self.assertRaisesRegex(ContractError, "IMPORT_NOT_FOUND"):
                    request_commit(batch.batch_key, actor, "bypass", self.commit_data(batch))

    def test_idempotency_replay_rechecks_current_permission(self):
        actor = User.objects.create(username="replay-all", admin_type=AdminType.ADMIN,
                                    problem_permission=ProblemPermission.ALL)
        batch = self.validated()
        data = self.commit_data(batch)
        request_commit(batch.batch_key, actor, "replay", data)
        actor.problem_permission = ProblemPermission.OWN
        actor.save(update_fields=["problem_permission"])
        with self.assertRaisesRegex(ContractError, "IMPORT_NOT_FOUND"):
            request_commit(batch.batch_key, actor, "replay", data)
        client = Client()
        client.force_login(actor)
        with patch("problem_import.views.commit_import_batch.send") as send:
            response = client.post("/api/admin/problem-import/batches/" + batch.batch_key + "/commit",
                                   json.dumps(data), content_type="application/json", HTTP_IDEMPOTENCY_KEY="replay")
            self.assertEqual(response.status_code, 404, response.content)
            send.assert_not_called()

    def test_concurrent_same_archive_keeps_one_owner_and_generic_conflict(self):
        owners = [User.objects.create(username="concurrent-owner-" + str(index), admin_type=AdminType.ADMIN,
                                      problem_permission=ProblemPermission.OWN) for index in range(2)]
        archive = package().getvalue()
        barrier = threading.Barrier(2)

        def upload(actor):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    batch, created = receive_archive(io.BytesIO(archive), actor)
                    return actor.pk, batch.pk, created
                except ContractError as error:
                    return actor.pk, error.code, error.status
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(upload, owners))
        batch = ProblemImportBatch.objects.get()
        self.assertIn((batch.uploaded_by_id, batch.pk, True), results)
        loser = next(actor for actor in owners if actor.pk != batch.uploaded_by_id)
        self.assertIn((loser.pk, "IMPORT_BATCH_CONFLICT", 409), results)
        self.assertEqual(list(Path(self.temp.name, "archive").iterdir()), [Path(batch.archive_path)])

    def test_commit_checks_locked_owner_before_idempotency_replay(self):
        owner = User.objects.create(username="locked-owner", admin_type=AdminType.ADMIN,
                                    problem_permission=ProblemPermission.OWN)
        batch, _ = receive_archive(package(), owner)
        batch = validate_batch(batch.pk)
        data = self.commit_data(batch)
        request_commit(batch.batch_key, owner, "locked", data)
        locking = threading.Event()

        def replay():
            close_old_connections()

            def observe(execute, sql, params, many, context):
                if "problem_import_batch" in sql and "FOR UPDATE" in sql:
                    locking.set()
                return execute(sql, params, many, context)

            try:
                with connection.execute_wrapper(observe):
                    try:
                        request_commit(batch.batch_key, owner, "locked", data)
                    except ContractError as error:
                        return error.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                locked = ProblemImportBatch.objects.select_for_update().get(pk=batch.pk)
                locked.uploaded_by = self.admin
                locked.save(update_fields=["uploaded_by"])
                future = pool.submit(replay)
                self.assertTrue(locking.wait(timeout=10))
            self.assertEqual(future.result(timeout=10), "IMPORT_NOT_FOUND")
        batch.refresh_from_db()
        self.assertEqual(len(batch.commit_operations), 1)

    def test_commit_rejects_coerced_json_types(self):
        from .views import CommitInput
        for payload in ({"allow_partial": "false", "problem_ids": [], "acknowledged_warning_codes": []},
                        {"allow_partial": False, "problem_ids": ["1"], "acknowledged_warning_codes": []},
                        {"allow_partial": False, "problem_ids": [True], "acknowledged_warning_codes": []}):
            self.assertFalse(CommitInput(data=payload).is_valid())

    def test_management_command_dry_run_report_and_warning_gate(self):
        filename = Path(self.temp.name, "input.zip")
        filename.write_bytes(package().read())
        output = Path(self.temp.name, "report.json")
        call_command("import_collected_problems", str(filename), "--dry-run", "--uploaded-by", self.admin.username,
                     "--report", str(output), stdout=io.StringIO())
        validator("problem-import-report-v1").validate(json.loads(output.read_text()))
        self.assertEqual(Problem.objects.count(), 0)
        with self.assertRaises(CommandError) as failure:
            call_command("import_collected_problems", str(filename), "--commit", "--uploaded-by", self.admin.username,
                         stdout=io.StringIO())
        self.assertEqual(failure.exception.returncode, 1)
        self.assertIn("IMPORT_WARNING_ACK_REQUIRED", str(failure.exception))

    def test_streaming_upload_limit_and_queue_replay(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        token = "b" * 32
        client.cookies["csrftoken"] = token
        endpoint = "/api/admin/problem-import/batches"
        with patch("problem_import.upload.WEB_LIMIT", 20):
            response = client.post(endpoint, {"archive": package()}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 413, response.content)
        self.assertEqual(ProblemImportBatch.objects.count(), 0)
        with patch("problem_import.views.validate_import_batch.send", side_effect=RuntimeError("broker unavailable")):
            response = client.post(endpoint, {"archive": package()}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 503, response.content)
        with patch("problem_import.views.validate_import_batch.send") as send:
            response = client.post(endpoint, {"archive": package()}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(ProblemImportBatch.objects.count(), 1)
        send.assert_called_once()
        self.assertNotIn("archive_path", response.json()["data"])

    def test_transient_validation_failure_is_replayable(self):
        batch, _ = receive_archive(package(), self.admin)
        with patch("problem_import.archive.Archive.verify_files", side_effect=OSError("transient")):
            with self.assertRaises(OSError):
                validate_batch(batch.pk)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "validating")
        self.assertEqual(validate_batch(batch.pk).status, "validated")

    def test_statement_only_never_creates_problem(self):
        def statement(records, entries, files):
            entries[0].update(directory=None, delivery_status="statement_only")
            for name in list(files):
                if name.startswith("1/"):
                    del files[name]
        batch = self.validated(package(mutate=statement))
        self.assertEqual(batch.status, "validated")
        self.assertEqual(batch.problems.get().import_status, "skipped")
        with self.assertRaisesRegex(ContractError, "IMPORT_NO_READY_PROBLEMS"):
            self.commit(batch)
        self.assertEqual(Problem.objects.count(), 0)

    def test_selected_subset_and_partial_validation(self):
        batch = self.validated(package(count=2))
        result = self.commit(batch, ids=[batch.problems.first().pk])
        self.assertEqual(result.imported_count, 1)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(result.status, "imported")

    def test_two_batches_concurrently_bind_same_source_once(self):
        batches = [self.validated(package("concurrent-" + str(index))) for index in range(2)]
        for batch in batches:
            request_commit(batch.batch_key, self.admin, "same-source", self.commit_data(batch))
        barrier = threading.Barrier(2)

        def worker(batch):
            close_old_connections()
            try:
                barrier.wait()
                return commit_batch(batch.pk).status
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(worker, batch) for batch in batches]
            self.assertEqual([result.result() for result in results], ["imported", "imported"])
        self.assertEqual(Problem.objects.count(), 1)
        self.assertEqual(ExternalProblemBinding.objects.count(), 1)
        self.assertEqual(len(list(Path(self.temp.name, "testcases").iterdir())), 1)

    def test_real_redis_actor_validation_and_commit(self):
        import dramatiq
        from dramatiq import Worker
        from .tasks import commit_import_batch, validate_import_batch

        batch, _ = receive_archive(package("async-batch"), self.admin)
        broker = dramatiq.get_broker()
        worker = Worker(broker, queues={"problem_import"}, worker_threads=1, worker_timeout=100)
        worker.start()
        try:
            validate_import_batch.send(str(batch.pk))
            broker.join("problem_import", timeout=15000)
            batch.refresh_from_db()
            self.assertEqual(batch.status, "validated")
            request_commit(batch.batch_key, self.admin, "async", self.commit_data(batch))
            commit_import_batch.send(str(batch.pk))
            broker.join("problem_import", timeout=15000)
            batch.refresh_from_db()
            self.assertEqual(batch.status, "imported")
            self.assertEqual(Problem.objects.count(), 1)
        finally:
            worker.stop(timeout=5000)

import io
import json
import tempfile
import threading
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import skipUnless
from uuid import UUID, uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils.timezone import now

from account.models import AdminType
from contest.models import Contest
from knowledge.tests import make_point, make_problem, make_user
from knowledge.services import update_point
from utils.contract_api import ContractError

from .adapters import embeddings, post_json
from .models import RagDocument, RagChunk
from .services import index_document, ingest_document, search


@contextmanager
def provider_fixture():
    """A local HTTP protocol fixture, deliberately not a real vector service."""
    state = {"requests": [], "rows": {}, "has_collection": False, "embedding_failures": 0,
             "invalid_embeddings": None, "fail_upsert": False, "hits": None, "on_upsert": None,
             "upsert_count": 0, "fail_after": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append((self.path, body))
            status = 200
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/embeddings")
                self.end_headers()
                return
            if self.path == "/slow-headers":
                try:
                    self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                    self.wfile.flush()
                    for _ in range(10):
                        time.sleep(.075)
                        self.wfile.write(b"x")
                        self.wfile.flush()
                    self.wfile.write(b"\r\nContent-Length: 2\r\n\r\n{}")
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if self.path == "/trickle":
                time.sleep(.25)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "2")
                self.end_headers()
                try:
                    self.wfile.write(b"{")
                    self.wfile.flush()
                    time.sleep(.35)
                    self.wfile.write(b"}")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if self.path == "/slow":
                time.sleep(.25)
                result = {"data": []}
            elif self.path == "/embeddings":
                if state["embedding_failures"]:
                    state["embedding_failures"] -= 1
                    status, result = 503, {"message": "secret-provider-body"}
                elif state["invalid_embeddings"] is not None:
                    result = {"data": state["invalid_embeddings"]}
                else:
                    result = {"data": [{"index": i, "embedding": [1.0, .25, .5]} for i in range(len(body["input"]))]}
            elif self.path.endswith("collections/has"):
                result = {"code": 0, "data": {"has": state["has_collection"]}}
            elif self.path.endswith("collections/create"):
                state["has_collection"] = True
                result = {"code": 0, "data": {}}
            elif self.path.endswith("entities/upsert"):
                state["upsert_count"] += 1
                if state["on_upsert"]:
                    callback, state["on_upsert"] = state["on_upsert"], None
                    callback()
                if state["fail_upsert"] or (state["fail_after"] is not None and state["upsert_count"] > state["fail_after"]):
                    status, result = 503, {"message": "secret-provider-body"}
                else:
                    state["rows"].update({row["id"]: row for row in body["data"]})
                    result = {"code": 0, "data": {"upsertCount": len(body["data"])}}
            elif self.path.endswith("entities/delete"):
                document_id = json.loads(body["filter"].split(" == ", 1)[1])
                state["rows"] = {key: row for key, row in state["rows"].items() if row["document_id"] != document_id}
                result = {"code": 0, "data": {}}
            elif self.path.endswith("entities/search"):
                hits = state["hits"] if state["hits"] is not None else [
                    {"id": key, "content_hash": row["content_hash"], "distance": .8} for key, row in state["rows"].items()]
                result = {"code": 0, "data": hits}
            else:
                status, result = 404, {"message": "unknown route"}
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(json.dumps(result).encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = "http://127.0.0.1:{}".format(server.server_port)
    try:
        with override_settings(RAG_EMBEDDING_URL=url + "/embeddings", RAG_EMBEDDING_MODEL="fixture-embedding",
                               RAG_EMBEDDING_VERSION="fixture-v1", RAG_MILVUS_URL=url, RAG_MILVUS_COLLECTION="fixture_rag",
                               RAG_RETRIEVAL_BACKEND="milvus"):
            yield url, state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class RagHTTPDeadlineTests(SimpleTestCase):
    def test_trickling_headers_cannot_reset_the_http_deadline(self):
        with provider_fixture() as (url, state):
            started = time.monotonic()
            with self.assertRaises(ContractError) as caught:
                post_json(url + "/slow-headers", {}, timeout=.2)
            elapsed = time.monotonic() - started
            self.assertEqual(caught.exception.code, "AGENT_DEPENDENCY_NOT_READY")
            self.assertLess(elapsed, .35, "Header reads must share the remaining deadline")
            self.assertEqual(len(state["requests"]), 1)

    def test_body_reads_share_the_remaining_http_deadline(self):
        with provider_fixture() as (url, state):
            started = time.monotonic()
            with self.assertRaises(ContractError) as caught:
                post_json(url + "/trickle", {}, timeout=.4)
            elapsed = time.monotonic() - started
            self.assertEqual(caught.exception.code, "AGENT_DEPENDENCY_NOT_READY")
            self.assertLess(elapsed, .55, "Each body read must use the remaining deadline")
            self.assertEqual(len(state["requests"]), 1)


class RagTests(TestCase):
    def setUp(self):
        self.admin = make_user("rag_admin")
        self.student = make_user("rag_student", AdminType.REGULAR_USER)
        self.point = make_point("binary_search", self.admin)
        self.problem = make_problem(self.admin)

    def payload(self, **kwargs):
        data = {"title": "Binary search", "source_type": "textbook", "source_id": "chapter-1",
                "content": "Binary search maintains a shrinking interval. 二分查找保持区间不变式。",
                "access_scope": "student", "status": "active", "metadata": {"knowledge_id": self.point.pk}}
        data.update(kwargs)
        return data

    def assert_error(self, code, fn):
        with self.assertRaises(ContractError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_ingestion_permissions_active_references_and_plain_text_cleaning(self):
        self.assert_error("AGENT_PERMISSION_DENIED", lambda: ingest_document(self.student, self.payload()))
        self.point.status = "draft"
        self.point.save()
        self.assert_error("AGENT_NOT_FOUND", lambda: ingest_document(self.admin, self.payload()))
        self.point.status = "active"
        self.point.save()
        doc, created = ingest_document(self.admin, self.payload(title="<b>查找</b>", content="<p>二分查找</p>"))
        self.assertTrue(created)
        self.assertEqual((doc.title, doc.content), ("查找", "二分查找"))
        self.assertEqual(doc.chunks.get().metadata["knowledge_id"], self.point.pk)
        template, _ = ingest_document(self.admin, self.payload(source_id="template", metadata={
            "knowledge_id": self.point.pk, "algorithm_template": "保持区间不变式",
            "complexity_target": {"time": "O(log n)", "space": "O(1)"}}))
        self.assertEqual(template.metadata["complexity_target"]["time"], "O(log n)")

    def test_idempotent_metadata_update_and_pending_revision_preserve_live_document(self):
        doc, _ = ingest_document(self.admin, self.payload())
        doc.chunks.update(embedding_id=str(doc.chunks.get().pk), embedding_model="model", embedding_version="v1")
        same, created = ingest_document(self.admin, self.payload())
        self.assertFalse(created)
        self.assertEqual(same.pk, doc.pk)
        self.assertEqual(same.chunks.get().embedding_model, "model")
        revised, _ = ingest_document(self.admin, self.payload(content="new pending content", status="pending"))
        doc.refresh_from_db()
        self.assertEqual(doc.status, "active")
        activated, created = ingest_document(self.admin, self.payload(content="new pending content", status="active"))
        self.assertEqual(activated.pk, revised.pk)
        self.assertFalse(created)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "disabled")
        locked, created = ingest_document(self.admin, self.payload(content="new pending content", access_scope="admin"))
        self.assertFalse(created)
        self.assertEqual(locked.access_scope, "admin")
        self.assertIsNone(locked.chunks.get().embedding_id)

    def test_unsafe_solutions_metadata_and_urls_are_rejected(self):
        for text in ("#include <iostream>\nint main() {}", "def solve():\n    print(input())", "api_key=abcdefghijk",
                     "a,b=map(int,input().split())\nprint(a+b)", '{"hint":"print(1)","contains_full_solution":false}'):
            self.assert_error("AGENT_OUTPUT_BLOCKED", lambda: ingest_document(self.admin, self.payload(content=text)))
        self.assert_error("AGENT_OUTPUT_BLOCKED", lambda: ingest_document(self.admin, self.payload(
            source_type="solution", metadata={"problem_id": self.problem._id})))
        for url in ("file:///etc/passwd", "javascript:alert(1)", "https://user:password@example.com/doc", "https://example.com/\nheader"):
            self.assert_error("AGENT_INPUT_INVALID", lambda: ingest_document(self.admin, self.payload(source_url=url)))
        self.assert_error("AGENT_INPUT_INVALID", lambda: ingest_document(self.admin, self.payload(metadata={"knowledge_id": True})))
        self.assertFalse(RagDocument.objects.exists())

    def test_code_remains_admin_only_and_legacy_student_hits_are_filtered(self):
        code = "a,b=map(int,input().split())\nprint(a+b)"
        private, _ = ingest_document(self.admin, self.payload(access_scope="admin", content=code))
        self.assertEqual(private.content, code)
        self.assert_error("AGENT_OUTPUT_BLOCKED", lambda: ingest_document(self.admin, self.payload(
            metadata={"knowledge_id": self.point.pk, "algorithm_template": code})))
        doc, _ = ingest_document(self.admin, self.payload(source_id="legacy-student"))
        RagChunk.objects.filter(document=doc).update(content="二分查找\n" + code)
        self.assertEqual(search("二分", self.point.pk)["hits"], [])
        RagChunk.objects.filter(document=doc).update(content="二分查找保持区间不变式")
        RagDocument.objects.filter(pk=doc.pk).update(title=code)
        self.assertEqual(search("二分", self.point.pk)["hits"], [])

    @skipUnless(connection.vendor == "postgresql", "Real PostgreSQL full-text search")
    @override_settings(RAG_RETRIEVAL_BACKEND="postgres")
    def test_postgres_search_rechecks_hidden_problems_solutions_and_inactive_knowledge(self):
        doc, _ = ingest_document(self.admin, self.payload(metadata={"knowledge_id": self.point.pk, "problem_id": self.problem._id}))
        for source_id, scope, source_type in (("private", "admin", "textbook"), ("solution", "admin", "solution")):
            ingest_document(self.admin, self.payload(source_id=source_id, access_scope=scope, source_type=source_type,
                                                     metadata={"knowledge_id": self.point.pk, "problem_id": self.problem._id}))
        result = search("二分", self.point.pk)
        self.assertEqual([item["chunk_id"] for item in result["hits"]], [str(doc.chunks.get().pk)])
        self.assertEqual(result["retrieval_version"], "postgres-fts-lexical-v1")
        self.problem.visible = False
        self.problem.save()
        self.assertEqual(search("二分", self.point.pk)["hits"], [])
        self.assert_error("AGENT_PROBLEM_NOT_FOUND", lambda: search("二分", self.point.pk, self.problem._id))
        self.point.status = "deprecated"
        self.point.save()
        self.assert_error("AGENT_NOT_FOUND", lambda: search("二分", self.point.pk))

    @skipUnless(connection.vendor == "postgresql", "Real PostgreSQL full-text search")
    @override_settings(RAG_RETRIEVAL_BACKEND="postgres")
    def test_postgres_chinese_substrings_and_literal_wildcards(self):
        doc, _ = ingest_document(self.admin, self.payload(content="多叉树的路径包含前缀和算法。百分率为100%，标记rate_%\\value。"))
        expected = [str(doc.chunks.get().pk)]
        for query in ("缀", "前缀", "前缀和", "包含前缀和", "100%", "rate_%\\value"):
            self.assertEqual([hit["chunk_id"] for hit in search(query, self.point.pk)["hits"]], expected, query)
        for query in ("100_", "rate_%/value", "不存在"):
            self.assertEqual(search(query, self.point.pk)["hits"], [], query)

    @skipUnless(connection.vendor == "postgresql", "Real PostgreSQL full-text search")
    @override_settings(RAG_RETRIEVAL_BACKEND="postgres")
    def test_postgres_english_multiword_rank_and_deduplication(self):
        ids = {}
        for source, content in (
                ("exact", "Binary invariant. Binary invariant."),
                ("separated", "An invariant guides each shrinking binary interval."),
                ("literal", "prebinary invariantly"),
                ("partial", "binary search has no other matching token")):
            doc, _ = ingest_document(self.admin, self.payload(source_id=source, content=content))
            ids[source] = str(doc.chunks.get().pk)
        hits = search("BINARY invariant", self.point.pk)["hits"]
        self.assertEqual([hit["chunk_id"] for hit in hits], [ids["exact"], ids["separated"], ids["literal"]])
        self.assertGreater(hits[0]["score"], hits[1]["score"])
        self.assertGreater(hits[1]["score"], 0)
        self.assertAlmostEqual(hits[2]["score"], 0, places=15)

    @skipUnless(connection.vendor == "postgresql", "Real PostgreSQL full-text search")
    @override_settings(RAG_RETRIEVAL_BACKEND="postgres")
    def test_postgres_same_title_ties_keep_uuid_order_and_five_hit_limit(self):
        for number in (9, 2, 7, 1, 8, 3, 6):
            doc, _ = ingest_document(self.admin, self.payload(source_id="tie-{}".format(number), content="区间不变式检查"))
            doc.chunks.update(id=UUID(int=number))
        hits = search("不变式", self.point.pk)["hits"]
        self.assertEqual([hit["chunk_id"] for hit in hits], [str(UUID(int=n)) for n in (1, 2, 3, 6, 7)])
        self.assertTrue(all(hit["score"] == 0 and hit["title"] == "Binary search" for hit in hits))

    @skipUnless(connection.vendor == "postgresql", "Real PostgreSQL full-text search")
    @override_settings(RAG_RETRIEVAL_BACKEND="postgres")
    def test_postgres_both_branches_recheck_scope_and_all_attached_resources(self):
        other = make_point("rag_other", self.admin)
        doc, _ = ingest_document(self.admin, self.payload(
            content="binary invariant and 区间不变式检查。", metadata={"knowledge_id": other.pk, "problem_id": self.problem._id}))
        queries = ("binary invariant", "不变式")
        expected = [str(doc.chunks.get().pk)]
        for query in queries:
            self.assertEqual([hit["chunk_id"] for hit in search(query, self.point.pk, self.problem._id)["hits"]], expected)
            self.assertEqual(search(query, self.point.pk)["hits"], [])
        for field, value in (("access_scope", "teacher"), ("status", "pending"), ("source_type", "solution")):
            original = getattr(doc, field)
            setattr(doc, field, value)
            doc.save()
            for query in queries:
                self.assertEqual(search(query, self.point.pk, self.problem._id)["hits"], [])
            setattr(doc, field, original)
            doc.save()
        other.status = "deprecated"
        other.save()
        for query in queries:
            self.assertEqual(search(query, self.point.pk, self.problem._id)["hits"], [])
        other.status = "active"
        other.save()
        self.problem.visible = False
        self.problem.save()
        for query in queries:
            self.assertEqual(search(query, other.pk)["hits"], [])

    def test_hidden_and_contest_problem_binding_cannot_be_imported_as_public(self):
        self.problem.visible = False
        self.problem.save()
        self.assert_error("AGENT_PROBLEM_NOT_FOUND", lambda: ingest_document(self.admin, self.payload(
            source_type="problem", metadata={"problem_id": self.problem._id})))
        self.assert_error("AGENT_INPUT_INVALID", lambda: ingest_document(self.admin, self.payload(source_type="problem")))
        contest = Contest.objects.create(title="Exam", description="", real_time_rank=False, rule_type="ACM",
                                         start_time=now(), end_time=now() + timedelta(hours=1), created_by=self.admin)
        self.problem.visible = True
        self.problem.contest = contest
        self.problem.save()
        self.assert_error("AGENT_PROBLEM_NOT_FOUND", lambda: ingest_document(self.admin, self.payload(
            source_type="problem", metadata={"problem_id": self.problem._id})))

    def test_http_retry_timeout_redirect_and_embedding_schema_fail_closed(self):
        with provider_fixture() as (url, state):
            state["embedding_failures"] = 1
            self.assertEqual(len(embeddings(["text"])), 1)
            self.assertEqual(len(state["requests"]), 2)
            self.assert_error("AGENT_DEPENDENCY_NOT_READY", lambda: post_json(url + "/slow", {}, timeout=.1))
            self.assert_error("AGENT_DEPENDENCY_NOT_READY", lambda: post_json(url + "/redirect", {}))
            self.assertEqual(sum(path == "/redirect" for path, _ in state["requests"]), 1)
            for rows in ([{"index": 1, "embedding": [1.0]}], [{"index": 0, "embedding": [float("nan")]}],
                         [{"index": 0, "embedding": [True]}], [{"index": False, "embedding": [1.0]}],
                         [{"index": 0, "embedding": [10 ** 1000]}]):
                state["invalid_embeddings"] = rows
                self.assert_error("AGENT_DEPENDENCY_NOT_READY", lambda: embeddings(["text"]))
        with override_settings(RAG_EMBEDDING_URL="file:///etc/passwd", RAG_EMBEDDING_MODEL="fixture"):
            self.assert_error("AGENT_DEPENDENCY_NOT_READY", lambda: embeddings(["text"]))
        self.assert_error("AGENT_DEPENDENCY_NOT_READY", lambda: search("binary", self.point.pk, timeout=0))

    def test_real_http_index_retry_resume_namespace_and_disabled_cleanup(self):
        doc, _ = ingest_document(self.admin, self.payload())
        with provider_fixture() as (_, state):
            state["fail_upsert"] = True
            self.assert_error("AGENT_DEPENDENCY_NOT_READY", lambda: index_document(doc.pk, create_collection=True))
            self.assertIsNone(doc.chunks.get().embedding_id)
            state["fail_upsert"] = False
            self.assertEqual(index_document(doc.pk, create_collection=True), 1)
            self.assertEqual(index_document(doc.pk, create_collection=True), 1)
            self.assertEqual(len(state["rows"]), 1)
            result = search("binary", self.point.pk)
            self.assertEqual(len(result["hits"]), 1)
            request = next(body for path, body in state["requests"] if path.endswith("entities/search"))
            self.assertEqual(request["collectionName"], "fixture_rag")
            self.assertIn('embedding_model == "fixture-embedding"', request["filter"])
            self.assertIn('embedding_version == "fixture-v1"', request["filter"])
            create = next(body for path, body in state["requests"] if path.endswith("collections/create"))
            self.assertIs(create["autoID"], False)
            self.assertEqual(sum(path.endswith("collections/create") for path, _ in state["requests"]), 1)
            with override_settings(RAG_EMBEDDING_VERSION="new-version"):
                self.assertEqual(search("binary", self.point.pk)["hits"], [])
            doc.status = "disabled"
            doc.save()
            self.assertEqual(search("binary", self.point.pk)["hits"], [])
            self.assertEqual(index_document(doc.pk), 0)
            self.assertEqual(state["rows"], {})
            self.assertIsNone(doc.chunks.get().embedding_id)

    def test_malicious_or_stale_vector_hits_cannot_override_database_authority(self):
        doc, _ = ingest_document(self.admin, self.payload())
        chunk = doc.chunks.get()
        with provider_fixture() as (_, state):
            index_document(doc.pk)
            for bad in ("not-a-uuid", "x' or true"):
                state["hits"] = [{"id": bad, "content_hash": chunk.content_hash, "distance": .8}]
                self.assert_error("AGENT_DEPENDENCY_NOT_READY", lambda: search("binary", self.point.pk))
            state["hits"] = [{"id": str(chunk.pk), "content_hash": chunk.content_hash, "distance": float("nan")}]
            self.assert_error("AGENT_DEPENDENCY_NOT_READY", lambda: search("binary", self.point.pk))
            state["hits"] = [{"id": str(uuid4()), "content_hash": chunk.content_hash, "distance": .8},
                             {"id": str(chunk.pk), "content_hash": "0" * 64, "distance": .8}]
            self.assertEqual(search("binary", self.point.pk)["hits"], [])
            state["hits"] = [{"id": str(chunk.pk), "content_hash": chunk.content_hash, "distance": .8}]
            doc.access_scope = "admin"
            doc.save()
            self.assertEqual(search("binary", self.point.pk)["hits"], [])

    def test_partial_index_failure_can_resume_without_duplicate_vectors(self):
        doc, _ = ingest_document(self.admin, self.payload(content="Binary search invariant. " * 1700))
        self.assertGreater(doc.chunks.count(), 32)
        with provider_fixture() as (_, state):
            state["fail_after"] = 1
            self.assert_error("AGENT_DEPENDENCY_NOT_READY", lambda: index_document(doc.pk, create_collection=True))
            self.assertEqual(doc.chunks.filter(embedding_id__isnull=False).count(), 32)
            state["fail_after"] = None
            count = index_document(doc.pk, create_collection=True)
            self.assertEqual(count, doc.chunks.count())
            self.assertEqual(len(state["rows"]), count)
            self.assertFalse(doc.chunks.filter(embedding_id__isnull=True).exists())

    def test_management_commands_read_json_and_recover_index_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.json"
            path.write_text(json.dumps(self.payload()))
            output = io.StringIO()
            call_command("ingest_rag", str(path), actor=self.admin.pk, stdout=output)
            self.assertTrue(json.loads(output.getvalue())["created"])
            with self.assertRaises(CommandError):
                call_command("ingest_rag", str(path), actor=self.student.pk, stdout=io.StringIO())
            with self.assertRaises(CommandError):
                call_command("rebuild_rag_index", document="bad-id", stdout=io.StringIO())
            with provider_fixture():
                output = io.StringIO()
                call_command("rebuild_rag_index", create_collection=True, stdout=output)
                self.assertIn("Indexed chunks: 1", output.getvalue())


@skipUnless(connection.vendor == "postgresql", "Real PostgreSQL concurrency")
class RagConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin = make_user("rag_concurrent_admin")
        self.point = make_point("rag_concurrent_point", self.admin)
        self.payload = {"title": "Concurrency", "source_type": "textbook", "source_id": "concurrent",
                        "content": "binary search", "status": "active", "metadata": {"knowledge_id": self.point.pk}}

    def parallel(self, callbacks):
        barrier = threading.Barrier(2)

        def run(callback):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return ("ok", callback())
            except ContractError as exc:
                return (exc.status, exc.code)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, callback) for callback in callbacks]
            return [future.result(timeout=15) for future in futures]

    def test_ingestion_and_deprecation_cannot_both_commit(self):
        results = self.parallel([
            lambda: ingest_document(self.admin, self.payload),
            lambda: update_point(self.admin, self.point.code, {"version": 1, "status": "deprecated"}),
        ])
        self.assertEqual(sum(item[0] == "ok" for item in results), 1, results)
        self.point.refresh_from_db()
        self.assertEqual(RagDocument.objects.count(), int(self.point.status == "active"))

    def test_same_source_concurrent_ingestion_creates_one_document(self):
        results = self.parallel([lambda: ingest_document(self.admin, self.payload),
                                 lambda: ingest_document(self.admin, self.payload)])
        self.assertTrue(all(item[0] == "ok" for item in results))
        self.assertEqual(sum(item[1][1] for item in results), 1)
        self.assertEqual(RagDocument.objects.count(), 1)
        self.assertEqual(RagDocument.objects.get().chunks.count(), 1)

    def test_index_does_not_publish_markers_for_concurrently_changed_document(self):
        document, _ = ingest_document(self.admin, self.payload)

        def change_scope():
            close_old_connections()
            try:
                ingest_document(self.admin, dict(self.payload, access_scope="admin"))
            finally:
                connection.close()

        with provider_fixture() as (_, state):
            state["on_upsert"] = change_scope
            with self.assertRaises(ContractError) as caught:
                index_document(document.pk)
            self.assertEqual(caught.exception.code, "AGENT_DEPENDENCY_NOT_READY")
            self.assertIsNone(document.chunks.get().embedding_id)
            self.assertEqual(search("binary", self.point.pk)["hits"], [])

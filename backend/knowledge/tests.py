import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.query import QuerySet
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from jsonschema import Draft202012Validator

from account.models import AdminType, ProblemPermission, User
from problem.models import Problem
from utils.contract_api import ContractError

from . import queries, services
from .models import (KnowledgeDependency, KnowledgeDependencyChangeRequest, KnowledgeMappingBatch,
                     KnowledgePoint, KnowledgeReviewEvent, ProblemKnowledge)


def make_user(name, admin_type=AdminType.SUPER_ADMIN, permission=ProblemPermission.ALL):
    return User.objects.create(username=name, admin_type=admin_type, problem_permission=permission)


def make_point(code, creator, status="active", category="algorithm", level=2):
    return KnowledgePoint.objects.create(code=code, name=code, normalized_name=code, category=category,
                                         level=level, status=status, created_by=creator)


def make_problem(creator, display_id="P001", visible=True):
    return Problem.objects.create(_id=display_id, title="Problem " + display_id, description="private description",
                                  input_description="", output_description="", samples=[], test_case_id="private_testcase",
                                  test_case_score=[], languages=["Python3"], template={}, time_limit=1000, memory_limit=128,
                                  rule_type="ACM", difficulty="Low", created_by=creator, visible=visible)


def edge_data(source, target, **extra):
    return dict(operation="create", prerequisite_code=source.code, dependent_code=target.code,
                relation_type="required", weight=Decimal("0.500"), reason="建立依赖", **extra)


def mapping_data(point, base_version=0):
    return {"base_version": base_version,
            "mappings": [{"knowledge_code": point.code, "role": "primary", "weight": Decimal("0.500")}]}


@override_settings(ROOT_URLCONF="knowledge.tests_urls")
class KnowledgeAPITests(TestCase):
    def setUp(self):
        self.author = make_user("author")
        self.reviewer = make_user("reviewer")
        self.own = make_user("own", AdminType.ADMIN, ProblemPermission.OWN)
        self.all_admin = make_user("all", AdminType.ADMIN, ProblemPermission.ALL)
        self.none_admin = make_user("none", AdminType.ADMIN, ProblemPermission.NONE)
        self.student = make_user("student", AdminType.REGULAR_USER, ProblemPermission.NONE)
        self.a = make_point("a", self.author)
        self.b = make_point("b", self.author)
        self.c = make_point("c", self.author)
        self.problem = make_problem(self.own)
        self.client.force_login(self.author)

    def call(self, method, path, data=None, expected=200, client=None):
        response = getattr(client or self.client, method)("/api/" + path, data=json.dumps(data) if data is not None else None,
                                                          content_type="application/json")
        self.assertEqual(response.status_code, expected, response.content)
        self.assertEqual(response["X-API-Version"], "0.9.9")
        if expected == 204:
            self.assertEqual(response.content, b"")
            return None
        body = response.json()
        self.assertEqual(set(body), {"error", "data", "request_id"})
        self.assertEqual(response["X-Request-ID"], body["request_id"])
        return body

    def assert_snapshots(self):
        schema = json.loads((Path(__file__).resolve().parents[2] / "docs/schemas/knowledge-snapshot-schema-v1.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        for event in KnowledgeReviewEvent.objects.all():
            validator.validate(event.snapshot)

    def submit_dependency(self, source=None, target=None, **extra):
        data = edge_data(source or self.a, target or self.b)
        data["weight"] = 0.5
        data.update(extra)
        return self.call("post", "admin/knowledge-dependency-change-requests", data, 201)["data"]

    def review(self, object_type, obj, approve=True, user=None, expected=200):
        self.client.force_login(user or self.reviewer)
        key = obj.get("request_id", obj.get("review_batch_id"))
        data = {"expected_updated_time": obj["updated_time"]}
        if not approve:
            data["reason"] = "需要修正"
        return self.call("post", "admin/knowledge-reviews/{}/{}/{}".format(object_type, key, "approve" if approve else "reject"),
                         data, expected)

    def test_session_role_and_csrf_boundaries(self):
        anonymous = Client()
        for path in ("knowledge-points", "knowledge-graph", "admin/knowledge-points", "admin/knowledge-reviews"):
            self.call("get", path, expected=401, client=anonymous)
        self.author.open_api = True
        self.author.open_api_appkey = "appkey-only"
        self.author.save()
        response = anonymous.get("/api/knowledge-points", HTTP_APPKEY="appkey-only")
        self.assertEqual(response.status_code, 401)
        for user in (self.student, self.none_admin):
            self.client.force_login(user)
            self.call("get", "knowledge-points")
            self.call("get", "admin/knowledge-points", expected=403)
        self.client.force_login(self.all_admin)
        self.call("get", "admin/knowledge-points")
        self.call("get", "admin/knowledge-reviews", expected=403)
        self.call("post", "admin/knowledge-dependency-change-requests", {}, expected=403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.author)
        payload = {"code": "new", "name": "New", "description": "", "category": "basic", "level": 1}
        self.call("post", "admin/knowledge-points", payload, 403, csrf_client)
        token = "a" * 32
        csrf_client.cookies["csrftoken"] = token
        response = csrf_client.post("/api/admin/knowledge-points", data=json.dumps(payload), content_type="application/json",
                                    HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201, response.content)

    def test_point_normalization_unique_status_and_delete_audit(self):
        payload = {"code": "new", "name": "  Ａ\u2003 B  ", "description": "", "category": "basic", "level": 1,
                   "aliases": ["ＤＰ", "dp", "动态规划"], "metadata": {"course_chapter": "第一章", "display_order": 0}}
        created = self.call("post", "admin/knowledge-points", payload, 201)["data"]
        self.assertEqual((created["status"], created["version"], created["normalized_name"]), ("draft", 1, "a b"))
        self.assertEqual(created["aliases"], ["ＤＰ", "动态规划"])
        conflict = self.call("post", "admin/knowledge-points", dict(payload, code="other"), 409)
        self.assertEqual(conflict["error"], "KNOWLEDGE_NAME_CONFLICT")
        self.call("patch", "admin/knowledge-points/new", {"version": 1, "code": "renamed"}, 400)
        self.call("patch", "admin/knowledge-points/new", {"version": 1, "status": "deprecated"}, 409)
        self.call("patch", "admin/knowledge-points/new", {"version": 0, "name": "bad"}, 400)
        self.call("patch", "admin/knowledge-points/new", {"version": 1, "status": "active"})
        self.call("patch", "admin/knowledge-points/new", {"version": 1, "name": "outdated"}, 409)
        self.call("post", "admin/knowledge-points/new/delete", {"version": 2, "reason": "删除测试"}, 409)
        self.call("patch", "admin/knowledge-points/new", {"version": 2, "status": "deprecated"})
        self.call("get", "knowledge-points/new", expected=404)
        draft = make_point("draft", self.author, status="draft")
        self.call("post", "admin/knowledge-points/draft/delete", {"version": draft.version, "reason": "删除草稿"}, 204)
        event = KnowledgeReviewEvent.objects.get(object_type="knowledge_point")
        self.assertEqual(event.snapshot["before"]["code"], "draft")
        self.assertNotIn("description", event.snapshot["before"])
        self.assertFalse(KnowledgePoint.objects.filter(code="draft").exists())
        self.assert_snapshots()
        with self.assertRaises(TypeError):
            event.delete()

    def test_deprecated_point_only_allows_description_and_aliases(self):
        point = make_point("retired", self.author, status="deprecated")
        for field, value in (("name", "New name"), ("category", "graph"), ("level", 5),
                             ("metadata", {"display_order": 9}), ("status", "deprecated")):
            with self.subTest(field=field):
                result = self.call("patch", "admin/knowledge-points/retired", {"version": 1, field: value}, 409)
                self.assertEqual(result["error"], "KNOWLEDGE_STATE_CONFLICT")
                point.refresh_from_db()
                self.assertEqual((point.version, point.name, point.category, point.level, point.metadata),
                                 (1, "retired", "algorithm", 2, {}))
        result = self.call("patch", "admin/knowledge-points/retired", {
            "version": 1, "description": "保留历史说明", "aliases": ["旧称"]})["data"]
        self.assertEqual((result["version"], result["description"], result["aliases"]), (2, "保留历史说明", ["旧称"]))

    def test_dependency_create_update_delete_retains_original_history(self):
        create = self.submit_dependency()
        self.assertEqual(KnowledgeDependency.objects.count(), 0)
        self.review("dependency_change", create, user=self.author, expected=403)
        self.review("dependency_change", create, approve=False, user=self.author, expected=403)
        self.assertEqual(KnowledgeReviewEvent.objects.count(), 1)
        self.review("dependency_change", create)
        edge = KnowledgeDependency.objects.get()
        self.assertEqual(edge.created_by_id, self.reviewer.pk)
        self.client.force_login(self.author)
        update = self.submit_dependency(dependent_code="c", operation="update", target_dependency_id=edge.id, base_version=1)
        self.assertEqual(update["before"]["dependent_code"], "b")
        self.call("post", "admin/knowledge-dependency-change-requests", {
            "operation": "delete", "target_dependency_id": edge.id, "base_version": 1, "reason": "重复待审"}, 409)
        self.assertEqual(KnowledgeDependency.objects.get().dependent_id, self.b.id)
        self.review("dependency_change", update)
        edge.refresh_from_db()
        self.assertEqual((edge.version, edge.dependent_id), (2, self.c.id))
        self.client.force_login(self.author)
        delete = self.call("post", "admin/knowledge-dependency-change-requests", {
            "operation": "delete", "target_dependency_id": edge.id, "base_version": 2, "reason": "删除旧依赖"}, 201)["data"]
        edge_id = edge.id
        self.review("dependency_change", delete)
        self.assertFalse(KnowledgeDependency.objects.exists())
        for request in (update, delete):
            historical = self.call("get", "admin/knowledge-reviews/dependency_change/" + request["request_id"])["data"]["request"]
            self.assertIsNone(historical["target_dependency_id"])
            self.assertEqual(historical["original_target_id"], edge_id)
            self.assertEqual(historical["before"], request["before"])
        self.assertEqual(KnowledgeReviewEvent.objects.count(), 6)
        self.assert_snapshots()
        self.review("dependency_change", delete, expected=409)

    def test_dependency_cycle_input_and_reject_leave_no_partial_writes(self):
        for source, target in ((self.a, self.b), (self.b, self.c)):
            KnowledgeDependency.objects.create(prerequisite=source, dependent=target, relation_type="required", weight=.5,
                                               created_by=self.author)
        invalid = [({"operation": "create", "reason": "缺少字段"}, 400),
                   (dict(edge_data(self.a, self.a), weight=.5), 422),
                   (dict(edge_data(self.c, self.a), weight=.5), 422),
                   (dict(edge_data(self.a, self.c), weight=.5001), 400),
                   (dict(edge_data(self.a, self.c), weight="0.5"), 400),
                   (dict(edge_data(self.a, self.c), weight=.5, source="ai"), 400),
                   (dict(edge_data(self.a, self.c), weight=0), 422),
                   (dict(edge_data(self.a, self.c), weight=1.5), 422)]
        for payload, status in invalid:
            body = self.call("post", "admin/knowledge-dependency-change-requests", payload, status)
            if payload.get("weight") in (0, 1.5):
                self.assertEqual(body["error"], "KNOWLEDGE_WEIGHT_INVALID")
        self.assertFalse(KnowledgeDependencyChangeRequest.objects.exists())
        self.assertFalse(KnowledgeReviewEvent.objects.exists())
        create = self.submit_dependency(self.a, self.c)
        self.call("patch", "admin/knowledge-points/c", {"version": 1, "status": "deprecated"}, 409)
        self.review("dependency_change", create, approve=False)
        self.assertEqual(KnowledgeDependency.objects.count(), 2)

    def test_mapping_dual_versions_self_review_replacement_and_scope(self):
        url = "admin/problems/{}/knowledge-mappings".format(self.problem.pk)
        empty = self.call("get", url)["data"]
        self.assertEqual((empty["coverage_status"], empty["approved_version"], empty["pending_batch"]), ("unannotated", 0, None))
        self.client.force_login(self.own)
        initial = {"base_version": 0, "mappings": [{"knowledge_code": "a", "role": "primary", "weight": .4}]}
        first = self.call("put", url, initial, 202)["data"]
        self.assertFalse(ProblemKnowledge.objects.exists())
        self.assertEqual(self.call("get", url)["data"]["coverage_status"], "in_review")
        self.call("put", url, initial, 409)
        self.review("problem_mapping", first)
        current = ProblemKnowledge.objects.get()
        self.assertEqual((current.knowledge_point_id, current.review_status), (self.a.id, "approved"))
        self.client.force_login(self.author)
        second = self.call("put", url, dict(initial, base_version=1), 202)["data"]
        self.review("problem_mapping", second, user=self.author, expected=403)
        self.review("problem_mapping", second, approve=False)
        state = self.call("get", url)["data"]
        self.assertEqual((state["approved_version"], state["next_batch_version"]), (1, 3))
        third = self.call("put", url, {"base_version": 1, "mappings": [
            {"knowledge_code": "b", "role": "primary", "weight": .8},
            {"knowledge_code": "c", "role": "secondary", "weight": .8}]}, 202)["data"]
        self.assertEqual(ProblemKnowledge.objects.get().knowledge_point_id, self.a.id)
        # Reviewer submitted third, author must review it.
        self.review("problem_mapping", third, user=self.author)
        state = self.call("get", url)["data"]
        self.assertEqual((state["approved_version"], state["next_batch_version"]), (2, 4))
        self.assertEqual({m["knowledge_code"] for m in state["mappings"]}, {"b", "c"})
        previous = KnowledgeMappingBatch.objects.get(pk=first["review_batch_id"])
        self.assertEqual(previous.status, "superseded")
        self.assertEqual(previous.payload, first["mappings"])
        replaced = KnowledgeReviewEvent.objects.get(action="replaced")
        self.assertEqual(replaced.snapshot["status"], "superseded")
        self.assertEqual(replaced.snapshot["approved_version"], 1)
        self.assertEqual(KnowledgeReviewEvent.objects.filter(object_type="problem_mapping").count(), 7)
        self.assert_snapshots()
        foreign_problem = make_problem(self.author, "foreign")
        self.client.force_login(self.own)
        self.call("get", "admin/problems/{}/knowledge-mappings".format(foreign_problem.id), expected=404)
        self.call("put", "admin/problems/{}/knowledge-mappings".format(foreign_problem.id), initial, 404)

    def test_mapping_validation_and_deprecation_references(self):
        url = "admin/problems/{}/knowledge-mappings".format(self.problem.id)
        for mappings in ([{"knowledge_code": "a", "role": "secondary", "weight": .5}],
                         [{"knowledge_code": "a", "role": "primary", "weight": .5}] * 2,
                         [{"knowledge_code": "missing", "role": "primary", "weight": .5}],
                         [{"knowledge_code": "a", "role": "primary", "weight": 0}],
                         [{"knowledge_code": "a", "role": "primary", "weight": .5}, {"knowledge_code": "b", "role": "secondary", "weight": 1.5}]):
            self.call("put", url, {"base_version": 0, "mappings": mappings}, 422)
        self.assertFalse(KnowledgeMappingBatch.objects.exists())
        first = self.call("put", url, {"base_version": 0, "mappings": [{"knowledge_code": "a", "role": "primary", "weight": .5}]}, 202)["data"]
        self.call("patch", "admin/knowledge-points/a", {"version": 1, "status": "deprecated"}, 409)
        self.review("problem_mapping", first, approve=False)
        self.call("patch", "admin/knowledge-points/a", {"version": 1, "status": "deprecated"})
        self.assertEqual(KnowledgeMappingBatch.objects.get().payload[0]["knowledge_code"], "a")

    def test_public_projection_filters_and_admin_counts_are_consistent(self):
        hidden = make_problem(self.author, "hidden", visible=False)
        other = make_problem(self.author, "P002")
        draft = make_point("draft", self.author, status="draft")
        for problem in (self.problem, hidden, other):
            ProblemKnowledge.objects.create(problem=problem, knowledge_point=self.a, role="primary", weight=.5, reviewed_by=self.reviewer)
        KnowledgeDependency.objects.create(prerequisite=self.a, dependent=self.b, relation_type="required", weight=.5,
                                           created_by=self.author)
        self.client.force_login(self.student)
        detail = self.call("get", "knowledge-points/a")["data"]
        self.assertEqual(set(detail), {"code", "name", "description", "category", "level", "aliases", "prerequisites",
                                       "dependents", "related_problems", "prerequisite_count", "dependent_count"})
        self.assertEqual([item["display_id"] for item in detail["related_problems"]], ["P001", "P002"])
        self.call("get", "knowledge-points/" + draft.code, expected=404)
        self.call("get", "knowledge-points?status=draft", expected=400)
        self.call("get", "knowledge-graph?unknown=true", expected=400)
        self.call("get", "knowledge-points?page_size=101", expected=400)
        self.client.force_login(self.own)
        listing = self.call("get", "admin/knowledge-points")["data"]
        item = next(item for item in listing["items"] if item["code"] == "a")
        detail = self.call("get", "admin/knowledge-points/a")["data"]
        self.assertEqual(item["related_problem_count"], detail["related_problems"]["total"])
        self.assertEqual(item["related_problem_count"], 1)
        self.assertEqual(detail["capabilities"], ["view"])
        self.assertEqual(detail["knowledge_point"]["created_by"]["id"], self.author.id)

    def assert_public_contract(self, body, schema):
        from openapi_schema_validator import OAS30Validator
        spec = json.loads((Path(__file__).resolve().parents[2] / "docs/openapi/knowledge-api-v1.yaml").read_text(encoding="utf-8"))
        OAS30Validator({"$ref": "#/components/schemas/" + schema, "components": spec["components"]}).validate(body)

    def test_public_detail_preserves_small_arrays_and_requires_explicit_pagination_for_large_sets(self):
        problems = [make_problem(self.author, "page{:03d}".format(i)) for i in range(100)]
        ProblemKnowledge.objects.bulk_create([ProblemKnowledge(problem=p, knowledge_point=self.a, role="primary", weight=.5,
                                                               reviewed_by=self.reviewer) for p in problems])
        self.client.force_login(self.student)
        body = self.call("get", "knowledge-points/a")
        self.assertEqual(len(body["data"]["related_problems"]), 100)
        self.assert_public_contract(body, "PublicKnowledgeEnvelope")
        extra = make_problem(self.author, "page100")
        ProblemKnowledge.objects.create(problem=extra, knowledge_point=self.a, role="primary", weight=.5, reviewed_by=self.reviewer)
        with CaptureQueriesContext(connection) as captured:
            body = self.call("get", "knowledge-points/a", expected=409)
        self.assertEqual(body["error"], "KNOWLEDGE_PAGINATION_REQUIRED")
        self.assertEqual(body["data"]["details"]["collections"], ["related_problems"])
        self.assertEqual(body["data"]["details"]["endpoints"]["related_problems"], "/api/knowledge-points/a/related-problems")
        self.assert_public_contract(body, "ErrorEnvelope")
        reads = [q["sql"] for q in captured if 'FROM "problem_knowledge"' in q["sql"]]
        self.assertEqual(len(reads), 1)
        self.assertIn("LIMIT 101", reads[0])
        self.assertNotIn('"problem"."description"', reads[0])
        body = self.call("get", "knowledge-points/a?include_collections=false")
        self.assertEqual([body["data"][key] for key in ("prerequisites", "dependents", "related_problems")], [[], [], []])
        self.assert_public_contract(body, "PublicKnowledgeEnvelope")
        for query in ("include_collections=0", "include_collections=False", "include_collections=null",
                      "include_collections=false&include_collections=true", "page=1"):
            self.call("get", "knowledge-points/a?" + query, expected=400)

    def test_public_related_problem_pages_filter_before_count_and_preserve_sort(self):
        from datetime import timedelta
        from django.utils import timezone
        from contest.models import Contest
        problems = [make_problem(self.author, "item{:03d}".format(i)) for i in reversed(range(103))]
        hidden = make_problem(self.author, "AAA-hidden", visible=False)
        contest = Contest.objects.create(title="Private contest", description="", created_by=self.author,
                                         start_time=timezone.now(), end_time=timezone.now()+timedelta(hours=1),
                                         rule_type="ACM", real_time_rank=True)
        contest_problem = make_problem(self.author, "AAA-contest")
        contest_problem.contest = contest
        contest_problem.save(update_fields=["contest"])
        ProblemKnowledge.objects.bulk_create([ProblemKnowledge(problem=p, knowledge_point=self.a, role="primary", weight=.5,
                                                               reviewed_by=self.reviewer) for p in problems + [hidden, contest_problem]])
        pending = make_problem(self.author, "AAA-pending")
        services.submit_mapping(self.author, pending.pk, mapping_data(self.a), "public-page-pending")
        self.client.force_login(self.student)
        identifiers = []
        for page in (1, 2, 3, 4):
            body = self.call("get", "knowledge-points/a/related-problems?page={}&page_size=40".format(page))
            self.assert_public_contract(body, "PublicProblemPageEnvelope")
            self.assertEqual((body["data"]["page"], body["data"]["page_size"], body["data"]["total"]), (page, 40, 103))
            identifiers += [item["display_id"] for item in body["data"]["items"]]
            for item in body["data"]["items"]:
                self.assertEqual(set(item), {"display_id", "title"})
            self.assertNotIn("AAA-", json.dumps(body))
        self.assertEqual(identifiers, ["item{:03d}".format(i) for i in range(103)])
        for actor in (self.own, self.none_admin, self.author):
            self.client.force_login(actor)
            self.assertEqual(self.call("get", "knowledge-points/a/related-problems")["data"]["total"], 103)
        problems[0].visible = False
        problems[0].save(update_fields=["visible"])
        self.assertEqual(self.call("get", "knowledge-points/a/related-problems")["data"]["total"], 102)
        for query in ("page=0", "page=-1", "page_size=101", "page_size=0", "page=1&page=2", "status=all", "page=1.2"):
            self.call("get", "knowledge-points/a/related-problems?" + query, expected=400)
        for status in ("draft", "deprecated"):
            point = make_point("page_" + status, self.author, status=status)
            self.call("get", "knowledge-points/" + point.code + "/related-problems", expected=404)
        self.call("get", "knowledge-points/missing/related-problems", expected=404)
        self.client.logout()
        self.call("get", "knowledge-points/a/related-problems", expected=401)

    def test_public_dependency_pages_and_opt_out_counts_are_bounded(self):
        outgoing = [make_point("out{:03d}".format(i), self.author) for i in reversed(range(101))]
        inactive = make_point("inactive_neighbor", self.author, status="deprecated")
        KnowledgeDependency.objects.bulk_create([KnowledgeDependency(prerequisite=self.a, dependent=p, relation_type="required",
                                                                     weight=.5, created_by=self.author) for p in outgoing + [inactive]])
        for source in (self.b, self.c):
            KnowledgeDependency.objects.create(prerequisite=source, dependent=self.a, relation_type="required", weight=.5, created_by=self.author)
        self.client.force_login(self.student)
        error = self.call("get", "knowledge-points/a", expected=409)
        self.assertEqual(error["data"]["details"]["collections"], ["dependents"])
        self.assertEqual(error["data"]["details"]["endpoints"]["dependents"], "/api/knowledge-points/a/dependencies?direction=dependents")
        body = self.call("get", "knowledge-points/a?include_collections=false")
        self.assertEqual((body["data"]["prerequisite_count"], body["data"]["dependent_count"]), (2, 101))
        self.assertEqual(body["data"]["dependents"], [])
        first = self.call("get", "knowledge-points/a/dependencies")
        self.assertEqual([item["code"] for item in first["data"]["items"]], ["b", "c"])
        second = self.call("get", "knowledge-points/a/dependencies?direction=dependents&page=2&page_size=100")
        self.assertEqual((second["data"]["total"], [item["code"] for item in second["data"]["items"]]), (101, ["out100"]))
        self.assert_public_contract(first, "PublicDependencyPageEnvelope")
        self.assert_public_contract(second, "PublicDependencyPageEnvelope")
        self.assertEqual(set(second["data"]["items"][0]), {"code", "name", "relation_type", "weight"})
        for query in ("direction=both", "direction=dependents&direction=prerequisites", "page_size=101"):
            self.call("get", "knowledge-points/a/dependencies?" + query, expected=400)
        self.call("get", "knowledge-points/inactive_neighbor/dependencies", expected=404)
        self.client.logout()
        self.call("get", "knowledge-points/a/dependencies", expected=401)

    def test_graph_bidirectional_filter_after_walk_truncation_and_edge_version(self):
        self.a.category = "basic"
        self.a.save()
        for source, target in ((self.a, self.b), (self.b, self.c)):
            KnowledgeDependency.objects.create(prerequisite=source, dependent=target, relation_type="required", weight=.5,
                                               created_by=self.author)
        result = self.call("get", "knowledge-graph?root_code=b&depth=1&category=basic")["data"]
        self.assertEqual({node["code"] for node in result["nodes"]}, {"a", "b"})
        self.assertTrue(all("id" not in edge for edge in result["edges"]))
        self.assertTrue(all("category" in node for node in result["nodes"]))
        edge = self.call("get", "admin/knowledge-graph")["data"]["edges"][0]
        data = self.call("get", "admin/knowledge-dependencies/" + str(edge["id"]))["data"]
        self.assertEqual(edge["version"], data["version"])
        KnowledgePoint.objects.bulk_create([KnowledgePoint(code="x{:03d}".format(i), name="x{:03d}".format(i),
                                                           normalized_name="x{:03d}".format(i), level=1, category="basic", status="active")
                                           for i in range(501)])
        graph = self.call("get", "knowledge-graph")["data"]
        self.assertTrue(graph["truncated"])
        self.assertEqual(len(graph["nodes"]), 500)
        self.assertEqual(graph["nodes"][-1]["code"], "x496")

    def test_summary_pagination_and_list_query_count_are_bounded(self):
        points = [make_point("n{:03d}".format(i), self.author) for i in range(101)]
        KnowledgeDependency.objects.bulk_create([KnowledgeDependency(prerequisite=self.a, dependent=point, relation_type="required",
                                                                     weight=.5, created_by=self.author) for point in points])
        detail = self.call("get", "admin/knowledge-points/a")["data"]
        self.assertEqual((len(detail["dependents"]["items"]), detail["dependents"]["total"]), (100, 101))
        page = self.call("get", "admin/knowledge-points/a/dependencies?direction=dependents&page=2&page_size=100")["data"]
        self.assertEqual([item["code"] for item in page["items"]], ["n100"])
        with CaptureQueriesContext(connection) as captured:
            queries.list_points(self.own, {"page": 1, "page_size": 100})
        self.assertEqual(len(captured), 3)

    def test_paged_mapping_counts_preserve_scope_and_do_not_use_correlated_problem_scans(self):
        from datetime import timedelta
        from django.utils import timezone
        from contest.models import Contest
        # Equal timestamps make this count-focused fixture paginate by code.
        KnowledgePoint.objects.update(updated_time=timezone.now())
        contest = Contest.objects.create(title="Count isolation", description="", created_by=self.author,
                                         start_time=timezone.now(), end_time=timezone.now()+timedelta(hours=1),
                                         rule_type="ACM", real_time_rank=True)
        hidden = make_problem(self.author, "hidden-count", visible=False)
        contest_problem = make_problem(self.own, "contest-count")
        contest_problem.contest = contest
        contest_problem.save(update_fields=["contest"])
        for problem in (self.problem, hidden, contest_problem):
            ProblemKnowledge.objects.create(problem=problem, knowledge_point=self.a, role="primary", weight=.5,
                                            reviewed_by=self.reviewer)
        ProblemKnowledge.objects.create(problem=self.problem, knowledge_point=self.b, role="secondary", weight=.5,
                                        reviewed_by=self.reviewer)
        for actor, expected in ((self.own, 1), (self.all_admin, 2), (self.author, 2)):
            with CaptureQueriesContext(connection) as captured:
                data = queries.list_points(actor, {"page": 1, "page_size": 1})
            self.assertEqual(data["items"][0]["related_problem_count"], expected)
            self.assertEqual(data["total"], 3)
            self.assertEqual(len(captured), 3)
            self.assertNotIn('"problem_knowledge"', captured[1]["sql"])
            self.assertIn("UNION ALL", captured[2]["sql"])
            self.assertEqual(queries.list_points(actor, {"page": 3, "page_size": 1})["items"][0]["related_problem_count"], 0)
            self.assertEqual(queries.list_points(actor, {"page": 4, "page_size": 1})["items"], [])
        with CaptureQueriesContext(connection) as captured:
            queries.list_points(self.student, {"page": 1, "page_size": 1}, public=True)
        self.assertEqual(len(captured), 2)
        self.assertTrue(all('"problem_knowledge"' not in query["sql"] for query in captured))

    def test_admin_list_sorts_recent_first_with_code_ties_while_public_keeps_code_order(self):
        from datetime import timedelta
        from django.utils import timezone
        latest = timezone.now()
        KnowledgePoint.objects.update(updated_time=latest)
        KnowledgePoint.objects.filter(pk=self.a.pk).update(updated_time=latest - timedelta(days=1))
        for actor in (self.author, self.all_admin, self.own):
            self.client.force_login(actor)
            first = self.call("get", "admin/knowledge-points?page=1&page_size=2")["data"]
            second = self.call("get", "admin/knowledge-points?page=2&page_size=2")["data"]
            self.assertEqual([point["code"] for point in first["items"]], ["b", "c"])
            self.assertEqual([point["code"] for point in second["items"]], ["a"])
            self.assertEqual((first["total"], second["total"]), (3, 3))
        self.client.force_login(self.student)
        public = self.call("get", "knowledge-points?page=1&page_size=3")["data"]
        self.assertEqual([point["code"] for point in public["items"]], ["a", "b", "c"])

    def test_review_queue_default_filters_history_and_capabilities(self):
        obj = self.submit_dependency()
        detail = self.call("get", "admin/knowledge-reviews/dependency_change/" + obj["request_id"])["data"]
        self.assertEqual(detail["capabilities"], [])
        queue = self.call("get", "admin/knowledge-reviews?keyword=author")["data"]
        self.assertEqual(queue["total"], 1)
        self.assertNotIn("proposed", queue["items"][0])
        self.assertNotIn("payload", queue["items"][0])
        self.call("get", "admin/knowledge-reviews?updated_from=2026-10-08T00:00:00Z&updated_to=2026-10-07T00:00:00Z", expected=400)
        self.review("dependency_change", obj, approve=False)
        self.assertEqual(self.call("get", "admin/knowledge-reviews")["data"]["total"], 0)
        self.assertEqual(self.call("get", "admin/knowledge-reviews?status=rejected&object_type=dependency_change")["data"]["total"], 1)

    def test_review_queue_survives_status_change_after_page_selection(self):
        change = services.submit_dependency(self.author, edge_data(self.a, self.b), "queue_dependency")
        batch = services.submit_mapping(self.author, self.problem.pk, mapping_data(self.a), "queue_mapping")
        fetch = QuerySet._fetch_all
        reviewed = False

        def review_after_selection(queryset):
            nonlocal reviewed
            fetch(queryset)
            rows = queryset._result_cache
            if not reviewed and rows and isinstance(rows[0], dict) and "queue_type" in rows[0]:
                reviewed = True
                for object_type, obj in (("dependency_change", change), ("problem_mapping", batch)):
                    services.review(self.reviewer, object_type, obj.pk, {"expected_updated_time": obj.updated_time}, True, "queue_approve")

        with patch.object(QuerySet, "_fetch_all", review_after_selection):
            queue = self.call("get", "admin/knowledge-reviews")["data"]
        self.assertTrue(reviewed)
        self.assertEqual(queue["total"], 2)
        self.assertEqual({row["object_key"] for row in queue["items"]}, {str(change.pk), str(batch.pk)})
        self.assertEqual([row["status"] for row in queue["items"]], ["approved", "approved"])

    def test_mixed_review_queue_pagination_has_no_duplicates(self):
        self.submit_dependency()
        services.submit_mapping(self.author, self.problem.pk, mapping_data(self.a), "mixed_queue")
        first = self.call("get", "admin/knowledge-reviews?page_size=1")["data"]
        second = self.call("get", "admin/knowledge-reviews?page_size=1&page=2")["data"]
        self.assertEqual(first["total"], 2)
        self.assertNotEqual(first["items"][0]["object_key"], second["items"][0]["object_key"])
        self.assertEqual({first["items"][0]["object_type"], second["items"][0]["object_type"]},
                         {"dependency_change", "problem_mapping"})

    def test_failed_audit_rolls_back_dependency_and_entire_mapping_replacement(self):
        change = services.submit_dependency(self.author, edge_data(self.a, self.b), "rollback_dependency")
        with patch("knowledge.services.record_event", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                services.review(self.reviewer, "dependency_change", change.pk,
                                {"expected_updated_time": change.updated_time}, True, "approve")
        self.assertFalse(KnowledgeDependency.objects.exists())
        change.refresh_from_db()
        self.assertEqual(change.status, "pending")
        first = services.submit_mapping(self.author, self.problem.pk, mapping_data(self.a), "first")
        services.review(self.reviewer, "problem_mapping", first.pk,
                        {"expected_updated_time": first.updated_time}, True, "first_approve")
        second = services.submit_mapping(self.author, self.problem.pk, mapping_data(self.b, 1), "second")
        original = services.record_event

        def fail_approval(*args, **kwargs):
            if args[3] == "approved":
                raise RuntimeError("audit unavailable")
            return original(*args, **kwargs)

        with patch("knowledge.services.record_event", side_effect=fail_approval):
            with self.assertRaises(RuntimeError):
                services.review(self.reviewer, "problem_mapping", second.pk,
                                {"expected_updated_time": second.updated_time}, True, "second_approve")
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.status, second.status), ("approved", "pending"))
        self.assertEqual(ProblemKnowledge.objects.get().knowledge_point_id, self.a.id)
        self.assertFalse(KnowledgeReviewEvent.objects.filter(action="replaced").exists())
        self.assertEqual(services.mapping_versions(self.problem.id), (1, 3))

    def test_cross_module_live_references_block_deprecation_and_all_references_block_deletion(self):
        from agent_service.models import ErrorPattern
        from learning.models import LearningPath, LearningPathStep, StudentKnowledgeState
        from problem_import.models import ExternalTagMapping

        pattern = ErrorPattern.objects.create(code="history_pattern", knowledge_point=self.b, verdict="WA",
                                              cause_short="边界错误", fix_direction="检查边界", review_status="approved")
        self.call("patch", "admin/knowledge-points/b", {"version": 1, "status": "deprecated"}, 409)
        pattern.review_status = "rejected"
        pattern.save()
        self.call("patch", "admin/knowledge-points/b", {"version": 1, "status": "deprecated"})
        state = StudentKnowledgeState.objects.create(user=self.student, knowledge_point=self.a)
        self.call("patch", "admin/knowledge-points/a", {"version": 1, "status": "deprecated"}, 409)
        state.delete()
        path = LearningPath.objects.create(user=self.student, target_knowledge=self.a)
        LearningPathStep.objects.create(learning_path=path, step_order=1, knowledge_point=self.a,
                                        reason_code="prerequisite", reason_text="先修知识")
        self.call("patch", "admin/knowledge-points/a", {"version": 1, "status": "deprecated"}, 409)
        path.status = "completed"
        path.save()
        self.call("patch", "admin/knowledge-points/a", {"version": 1, "status": "deprecated"})
        draft = make_point("external_draft", self.author, status="draft")
        ExternalTagMapping.objects.create(source_platform="source", source_tag="draft", normalized_source_tag="draft",
                                          unified_tag="draft", knowledge_point=draft, status="disabled")
        self.call("post", "admin/knowledge-points/external_draft/delete", {"version": 1, "reason": "清理草稿"}, 409)
        self.assertTrue(KnowledgePoint.objects.filter(pk=draft.pk).exists())
        self.assertFalse(KnowledgeReviewEvent.objects.filter(object_type="knowledge_point").exists())

    def test_json_references_in_rag_and_learning_outbox_obey_live_history_boundary(self):
        from learning.models import LearningSubmissionEvent
        from rag.models import RagChunk, RagDocument
        from submission.models import Submission

        document = RagDocument.objects.create(title="教材", source_type="textbook", content="知识说明", content_hash="a" * 64,
                                              status="active", metadata={"knowledge_id": self.a.pk})
        RagChunk.objects.create(document=document, chunk_index=0, content="知识说明", content_hash="a" * 64,
                                metadata={"knowledge_id": self.a.pk})
        self.call("patch", "admin/knowledge-points/a", {"version": 1, "status": "deprecated"}, 409)
        document.status = "disabled"
        document.save()
        submission = Submission.objects.create(problem=self.problem, user_id=self.student.id, username=self.student.username,
                                               code="", language="Python3")
        event = LearningSubmissionEvent.objects.create(submission=submission, user=self.student, fingerprint="b" * 64,
                                                       payload={"mappings": [{"knowledge_id": self.a.pk, "knowledge_code": "a",
                                                                              "weight": .5, "problem_rating": 1200}]})
        self.call("patch", "admin/knowledge-points/a", {"version": 1, "status": "deprecated"}, 409)
        event.status = "processed"
        event.save()
        self.call("patch", "admin/knowledge-points/a", {"version": 1, "status": "deprecated"})
        draft = make_point("rag_history", self.author, status="draft")
        document.metadata = {"knowledge_id": draft.pk}
        document.save()
        self.call("post", "admin/knowledge-points/rag_history/delete", {"version": 1, "reason": "不能丢失历史"}, 409)

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL history guards")
    def test_database_guards_keep_candidates_and_events_immutable(self):
        change = services.submit_dependency(self.author, edge_data(self.a, self.b), "immutable")
        batch = services.submit_mapping(self.author, self.problem.pk, mapping_data(self.a), "immutable")
        with self.assertRaises(IntegrityError), transaction.atomic():
            KnowledgeDependencyChangeRequest.objects.filter(pk=change.pk).update(proposed={})
        with self.assertRaises(IntegrityError), transaction.atomic():
            KnowledgeMappingBatch.objects.filter(pk=batch.pk).update(payload=[])
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE knowledge_review_event SET snapshot = '{}'::jsonb")
        change.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(change.proposed["prerequisite_code"], "a")
        self.assertEqual(batch.payload[0]["knowledge_code"], "a")
        self.assert_snapshots()


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL transaction locks")
class KnowledgeConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.author = make_user("thread_author")
        self.reviewer = make_user("thread_reviewer")
        self.reviewer2 = make_user("thread_reviewer2")
        self.a, self.b, self.c, self.d = [make_point(code, self.author) for code in "abcd"]
        self.problem = make_problem(self.author)

    def concurrent(self, functions):
        barrier = threading.Barrier(len(functions))

        def run(fn):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                result = fn()
                return ("ok", str(getattr(result, "pk", result)))
            except ContractError as exc:
                return (exc.status, exc.code)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(functions)) as executor:
            futures = [executor.submit(run, function) for function in functions]
            return [future.result(timeout=20) for future in futures]

    def approve(self, change, reviewer=None):
        return services.review(reviewer or self.reviewer, "dependency_change", change.pk,
                               {"expected_updated_time": change.updated_time}, True, "concurrent_review")

    def test_disjoint_endpoint_approvals_cannot_create_cycle(self):
        for source, target in ((self.a, self.b), (self.c, self.d)):
            KnowledgeDependency.objects.create(prerequisite=source, dependent=target, relation_type="required", weight=.5,
                                               created_by=self.author)
        first = services.submit_dependency(self.author, edge_data(self.b, self.c), "submit1")
        second = services.submit_dependency(self.author, edge_data(self.d, self.a), "submit2")
        results = self.concurrent([lambda: self.approve(first), lambda: self.approve(second, self.reviewer2)])
        self.assertEqual(sum(result[0] == "ok" for result in results), 1, results)
        self.assertIn((422, "KNOWLEDGE_DEPENDENCY_CYCLE"), results)
        self.assertEqual(KnowledgeDependency.objects.count(), 3)
        self.assertEqual(KnowledgeDependencyChangeRequest.objects.filter(status="pending").count(), 1)
        self.assertEqual(KnowledgeReviewEvent.objects.filter(action="approved").count(), 1)

    def test_same_request_has_exactly_one_reviewer(self):
        change = services.submit_dependency(self.author, edge_data(self.a, self.b), "submit")
        results = self.concurrent([lambda: self.approve(change), lambda: self.approve(change, self.reviewer2)])
        self.assertEqual(sum(result[0] == "ok" for result in results), 1, results)
        self.assertIn((409, "KNOWLEDGE_REVIEW_CONFLICT"), results)
        self.assertEqual(KnowledgeDependency.objects.count(), 1)
        self.assertEqual(KnowledgeReviewEvent.objects.count(), 2)

    def test_reference_submission_and_deprecation_cannot_both_commit(self):
        results = self.concurrent([
            lambda: services.submit_mapping(self.author, self.problem.pk, mapping_data(self.a), "submit"),
            lambda: services.update_point(self.reviewer, "a", {"version": 1, "status": "deprecated"}),
        ])
        self.assertEqual(sum(result[0] == "ok" for result in results), 1, results)
        self.a.refresh_from_db()
        if self.a.status == "deprecated":
            self.assertFalse(KnowledgeMappingBatch.objects.exists())
            self.assertFalse(KnowledgeReviewEvent.objects.exists())
        else:
            self.assertEqual(KnowledgeMappingBatch.objects.filter(status="pending").count(), 1)
            self.assertEqual(KnowledgeReviewEvent.objects.count(), 1)

    def test_two_mapping_submissions_preserve_one_pending_batch(self):
        results = self.concurrent([
            lambda: services.submit_mapping(self.author, self.problem.pk, mapping_data(self.a), "submit1"),
            lambda: services.submit_mapping(self.reviewer, self.problem.pk, mapping_data(self.b), "submit2"),
        ])
        self.assertEqual(sum(result[0] == "ok" for result in results), 1, results)
        self.assertIn((409, "KNOWLEDGE_REVIEW_CONFLICT"), results)
        self.assertEqual(KnowledgeMappingBatch.objects.count(), 1)
        self.assertFalse(ProblemKnowledge.objects.exists())

    def test_update_and_create_competing_for_same_pair_only_one_approves(self):
        edge = KnowledgeDependency.objects.create(prerequisite=self.a, dependent=self.b, relation_type="required", weight=.5,
                                                  created_by=self.author)
        update_data = edge_data(self.a, self.c)
        update_data.update(operation="update", target_dependency_id=edge.pk, base_version=1)
        update = services.submit_dependency(self.author, update_data, "update_submit")
        create = services.submit_dependency(self.author, edge_data(self.a, self.c), "create_submit")
        results = self.concurrent([lambda: self.approve(update), lambda: self.approve(create, self.reviewer2)])
        self.assertEqual(sum(result[0] == "ok" for result in results), 1, results)
        self.assertIn((409, "KNOWLEDGE_DEPENDENCY_EXISTS"), results)
        self.assertEqual(KnowledgeDependency.objects.filter(prerequisite=self.a, dependent=self.c).count(), 1)
        self.assertEqual(KnowledgeReviewEvent.objects.filter(action="approved").count(), 1)

    def test_same_mapping_batch_has_one_approval_and_one_current_set(self):
        batch = services.submit_mapping(self.author, self.problem.pk, mapping_data(self.a), "batch_submit")

        def approve(reviewer):
            return services.review(reviewer, "problem_mapping", batch.pk,
                                   {"expected_updated_time": batch.updated_time}, True, "batch_review")

        results = self.concurrent([lambda: approve(self.reviewer), lambda: approve(self.reviewer2)])
        self.assertEqual(sum(result[0] == "ok" for result in results), 1, results)
        self.assertIn((409, "KNOWLEDGE_REVIEW_CONFLICT"), results)
        self.assertEqual(ProblemKnowledge.objects.count(), 1)
        self.assertEqual(KnowledgeMappingBatch.objects.get().approved_version, 1)
        self.assertEqual(KnowledgeReviewEvent.objects.count(), 2)

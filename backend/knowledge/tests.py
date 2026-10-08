import json

from django.conf.urls import include, url
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings

from account.models import AdminType, ProblemPermission, User
from problem.models import Problem

from .models import KnowledgeDependency, KnowledgeMappingBatch, KnowledgePoint, KnowledgeReviewEvent, ProblemKnowledge


urlpatterns = [
    url(r"^api/admin/", include("knowledge.urls.admin")),
    url(r"^api/", include("knowledge.urls.public")),
]


@override_settings(ROOT_URLCONF="knowledge.tests")
class KnowledgeAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(username="owner", admin_type=AdminType.SUPER_ADMIN)
        self.reviewer = User.objects.create(username="reviewer", admin_type=AdminType.SUPER_ADMIN)
        self.student = User.objects.create(username="student")
        self.client.force_login(self.owner)

    def point(self, code, status="active", category="graph", level=1):
        return KnowledgePoint.objects.create(code=code, name=code, normalized_name=code, description="", category=category,
                                             level=level, status=status, created_by=self.owner)

    def problem(self, display_id="1001", owner=None, visible=True):
        return Problem.objects.create(_id=display_id, title="A+B", description="", input_description="", output_description="",
                                      samples=[], test_case_id="fixture", test_case_score=[], languages=["C++"], template={},
                                      created_by=owner or self.owner, time_limit=1000, memory_limit=128, rule_type="ACM",
                                      difficulty="Low", visible=visible)

    def post(self, path, data, user=None):
        if user:
            self.client.force_login(user)
        return self.client.post(path, data=json.dumps(data), content_type="application/json")

    def put(self, path, data, user=None):
        if user:
            self.client.force_login(user)
        return self.client.put(path, data=json.dumps(data), content_type="application/json")

    def test_public_requires_session_and_returns_only_active_visible_data(self):
        first = self.point("first")
        second = self.point("second")
        self.point("hidden", "draft")
        KnowledgeDependency.objects.create(prerequisite=first, dependent=second, relation_type="required", weight=1, created_by=self.owner)
        self.client.logout()
        self.assertEqual(self.client.get("/api/knowledge-points").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/knowledge-points").status_code, 401)
        self.client.force_login(self.student)
        result = self.client.get("/api/knowledge-points").json()["data"]
        self.assertEqual([item["code"] for item in result["items"]], ["first", "second"])
        self.assertEqual(self.client.get("/api/knowledge-points/hidden").status_code, 404)
        detail = self.client.get("/api/knowledge-points/second").json()["data"]
        self.assertEqual(detail["prerequisites"][0]["code"], "first")
        self.assertNotIn("status", detail)

    def test_graph_traverses_before_filter_and_keeps_root(self):
        root = self.point("root", category="basic")
        middle = self.point("middle", category="graph")
        end = self.point("end", category="basic")
        KnowledgeDependency.objects.create(prerequisite=end, dependent=middle, relation_type="required", weight=1, created_by=self.owner)
        KnowledgeDependency.objects.create(prerequisite=middle, dependent=root, relation_type="required", weight=1, created_by=self.owner)
        data = self.client.get("/api/knowledge-graph?root_code=root&depth=2&category=basic").json()["data"]
        self.assertEqual([node["code"] for node in data["nodes"]], ["root", "end"])
        self.assertEqual(data["edges"], [])

    def test_graph_caps_nodes_and_rejects_empty_root(self):
        points = [KnowledgePoint(code=f"p{i:03d}", name=f"p{i:03d}", normalized_name=f"p{i:03d}",
                                 description="", category="graph", level=1, status="active", created_by=self.owner)
                  for i in range(501)]
        KnowledgePoint.objects.bulk_create(points)
        response = self.client.get("/api/knowledge-graph")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(len(data["nodes"]), 500)
        self.assertTrue(data["truncated"])
        self.assertEqual(self.client.get("/api/knowledge-graph?root_code=").status_code, 400)

    def test_point_creation_normalization_and_deletion_conflict(self):
        payload = {"code": "intro", "name": "  Ａ   B ", "description": "intro", "category": "basic", "level": 1}
        created = self.post("/api/admin/knowledge-points", payload)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["data"]["normalized_name"], "a b")
        payload = {"code": "another", "name": "a b", "description": "", "category": "basic", "level": 1}
        duplicate = self.post("/api/admin/knowledge-points", payload)
        self.assertEqual(duplicate.status_code, 409)
        point = KnowledgePoint.objects.get(code="intro")
        payload = {"version": point.version, "reason": "not needed"}
        self.assertEqual(self.post("/api/admin/knowledge-points/intro/delete", payload).status_code, 204)
        active = self.point("active")
        payload = {"version": active.version, "reason": "not needed"}
        self.assertEqual(self.post("/api/admin/knowledge-points/active/delete", payload).status_code, 409)

    def test_dependency_request_requires_other_reviewer_and_prevents_cycle(self):
        self.point("first")
        self.point("second")
        payload = {"operation": "create", "reason": "learning order", "prerequisite_code": "first",
                   "dependent_code": "second", "relation_type": "required", "weight": 1}
        submitted = self.post("/api/admin/knowledge-dependency-change-requests", payload)
        self.assertEqual(submitted.status_code, 201)
        self.assertEqual(KnowledgeDependency.objects.count(), 0)
        item = submitted.json()["data"]
        action = "/api/admin/knowledge-reviews/dependency_change/{}/approve".format(item["request_id"])
        self.assertEqual(self.post(action, {"expected_updated_time": item["updated_time"]}).status_code, 403)
        rejected = action.replace("/approve", "/reject")
        self.assertEqual(self.post(rejected, {"expected_updated_time": item["updated_time"],
                                              "reason": "not valid"}).status_code, 403)
        self.assertEqual(KnowledgeDependency.objects.count(), 0)
        self.assertEqual(KnowledgeReviewEvent.objects.count(), 1)
        approved = self.post(action, {"expected_updated_time": item["updated_time"]}, self.reviewer)
        self.assertEqual(approved.status_code, 200, approved.content)
        self.assertEqual(KnowledgeDependency.objects.count(), 1)
        reverse = {**payload, "prerequisite_code": "second", "dependent_code": "first"}
        submitted = self.post("/api/admin/knowledge-dependency-change-requests", reverse, self.owner)
        item = submitted.json()["data"]
        action = "/api/admin/knowledge-reviews/dependency_change/{}/approve".format(item["request_id"])
        self.assertEqual(self.post(action, {"expected_updated_time": item["updated_time"]}, self.reviewer).status_code, 422)
        self.assertEqual(KnowledgeDependency.objects.count(), 1)

    def test_database_rejects_duplicate_and_self_loop_edges(self):
        first = self.point("first")
        second = self.point("second")
        KnowledgeDependency.objects.create(prerequisite=first, dependent=second, relation_type="required", weight=1,
                                           created_by=self.owner)
        with self.assertRaises(IntegrityError), transaction.atomic():
            KnowledgeDependency.objects.create(prerequisite=first, dependent=second, relation_type="recommended", weight=1,
                                               created_by=self.owner)
        with self.assertRaises(IntegrityError), transaction.atomic():
            KnowledgeDependency.objects.create(prerequisite=first, dependent=first, relation_type="required", weight=1,
                                               created_by=self.owner)

    def test_dependency_update_and_delete_take_effect_only_after_approval(self):
        first = self.point("first")
        second = self.point("second")
        self.point("third")
        edge = KnowledgeDependency.objects.create(prerequisite=first, dependent=second, relation_type="required", weight=1,
                                                  created_by=self.owner)
        payload = {"operation": "update", "reason": "better sequence", "target_dependency_id": edge.id,
                   "base_version": 1, "prerequisite_code": "first", "dependent_code": "third",
                   "relation_type": "recommended", "weight": 0.5}
        submitted = self.post("/api/admin/knowledge-dependency-change-requests", payload)
        self.assertEqual(submitted.status_code, 201)
        request_data = submitted.json()["data"]
        self.assertEqual(request_data["before"]["id"], edge.id)
        edge.refresh_from_db()
        self.assertEqual(edge.dependent.code, "second")
        path = "/api/admin/knowledge-reviews/dependency_change/{}/approve".format(request_data["request_id"])
        self.assertEqual(self.post(path, {"expected_updated_time": request_data["updated_time"]}, self.reviewer).status_code, 200)
        edge.refresh_from_db()
        self.assertEqual((edge.dependent.code, edge.version), ("third", 2))
        payload = {"operation": "delete", "reason": "obsolete relation", "target_dependency_id": edge.id, "base_version": 2}
        submitted = self.post("/api/admin/knowledge-dependency-change-requests", payload, self.owner)
        self.assertEqual(submitted.status_code, 201)
        request_data = submitted.json()["data"]
        self.assertTrue(KnowledgeDependency.objects.filter(id=edge.id).exists())
        path = "/api/admin/knowledge-reviews/dependency_change/{}/approve".format(request_data["request_id"])
        self.assertEqual(self.post(path, {"expected_updated_time": request_data["updated_time"]}, self.reviewer).status_code, 200)
        self.assertFalse(KnowledgeDependency.objects.filter(id=edge.id).exists())
        detail_path = "/api/admin/knowledge-reviews/dependency_change/{}".format(request_data["request_id"])
        detail = self.client.get(detail_path).json()["data"]
        self.assertEqual(detail["request"]["before"]["id"], edge.id)

    def test_status_and_version_protect_referenced_points(self):
        first = self.point("first")
        second = self.point("second")
        KnowledgeDependency.objects.create(prerequisite=first, dependent=second, relation_type="required", weight=1,
                                           created_by=self.owner)
        response = self.client.patch("/api/admin/knowledge-points/first", data=json.dumps({"version": 1, "status": "deprecated"}),
                                     content_type="application/json")
        self.assertEqual(response.status_code, 409)
        response = self.client.patch("/api/admin/knowledge-points/first", data=json.dumps({"version": 999, "name": "changed"}),
                                     content_type="application/json")
        self.assertEqual(response.status_code, 409)
        first.refresh_from_db()
        self.assertEqual(first.status, "active")
        self.assertFalse(KnowledgeReviewEvent.objects.exists())

    def test_mapping_batch_and_approved_version_are_independent(self):
        self.point("first")
        problem = self.problem()
        path = f"/api/admin/problems/{problem.id}/knowledge-mappings"
        item = {"knowledge_code": "first", "role": "primary", "weight": 1}
        first = self.put(path, {"base_version": 0, "mappings": [item]})
        self.assertEqual(first.status_code, 201)
        batch = first.json()["data"]
        review = "/api/admin/knowledge-reviews/problem_mapping/{}".format(batch["review_batch_id"])
        self.assertEqual(self.post(review + "/approve", {"expected_updated_time": batch["updated_time"]}).status_code, 403)
        approved = self.post(review + "/approve", {"expected_updated_time": batch["updated_time"]}, self.reviewer)
        self.assertEqual(approved.status_code, 200, approved.content)
        self.assertEqual(self.client.get(path).json()["data"]["approved_version"], 1)
        self.assertEqual(ProblemKnowledge.objects.filter(problem=problem).count(), 1)
        second = self.put(path, {"base_version": 1, "mappings": [item]}, self.owner).json()["data"]
        review = "/api/admin/knowledge-reviews/problem_mapping/{}".format(second["review_batch_id"])
        self.assertEqual(self.post(review + "/reject", {"expected_updated_time": second["updated_time"],
                                                        "reason": "needs review"}, self.reviewer).status_code, 200)
        self.assertEqual(self.client.get(path).json()["data"]["approved_version"], 1)
        third = self.put(path, {"base_version": 1, "mappings": [item]}, self.owner).json()["data"]
        self.assertEqual(third["batch_version"], 3)
        review = "/api/admin/knowledge-reviews/problem_mapping/{}".format(third["review_batch_id"])
        self.assertEqual(self.post(review + "/approve", {"expected_updated_time": third["updated_time"]}, self.reviewer).status_code, 200)
        self.assertEqual(self.client.get(path).json()["data"]["approved_version"], 2)
        self.assertEqual(KnowledgeMappingBatch.objects.get(id=third["review_batch_id"]).approved_version, 2)

    def test_owner_scope_and_public_problem_visibility(self):
        point = self.point("first")
        allowed = self.problem("1001")
        hidden = self.problem("1002", visible=False)
        for problem in (allowed, hidden):
            ProblemKnowledge.objects.create(problem=problem, knowledge_point=point, role="primary", weight=1,
                                            reviewed_by=self.reviewer)
        self.client.force_login(self.student)
        related = self.client.get("/api/knowledge-points/first").json()["data"]["related_problems"]
        self.assertEqual(related, [{"display_id": "1001", "title": "A+B"}])
        own_admin = User.objects.create(username="own_admin", admin_type=AdminType.ADMIN,
                                        problem_permission=ProblemPermission.OWN)
        self.client.force_login(own_admin)
        self.assertEqual(self.client.get(f"/api/admin/problems/{allowed.id}/knowledge-mappings").status_code, 404)
        self.assertEqual(self.client.get("/api/admin/knowledge-points").status_code, 200)
        detail = self.client.get("/api/admin/knowledge-points/first")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["related_problems"]["items"], [])
        self.assertEqual(self.client.get("/api/admin/knowledge-reviews").status_code, 403)

    def test_writes_require_csrf_token(self):
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        payload = {"code": "first", "name": "first", "description": "", "category": "basic", "level": 1}
        response = guarded.post("/api/admin/knowledge-points", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(KnowledgePoint.objects.exists())

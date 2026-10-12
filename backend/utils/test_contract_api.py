from django.test import override_settings
from django.urls import path
from rest_framework import serializers
from rest_framework.test import APIClient

from utils.api import APIView as LegacyAPIView
from utils.api.tests import APITestCase
from utils.contract_api import ContractAPIView, ContractError, ContractSerializer


class EchoSerializer(ContractSerializer):
    value = serializers.CharField(max_length=20)


class EchoView(ContractAPIView):
    error_prefix = "KNOWLEDGE"
    contract_version = "0.9.9"

    def get(self, request):
        return self.success({"user_id": request.user.id})

    def post(self, request):
        serializer = EchoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.success(serializer.validated_data, 201)

    def delete(self, request):
        return self.success(status=204)


class FailureView(ContractAPIView):
    def get(self, request):
        raise RuntimeError("provider credential or source code must never be logged")

    def post(self, request):
        raise ContractError("LEARNING_REFRESH_CONFLICT", "正在刷新", 409, retryable=True)


class LegacyView(LegacyAPIView):
    def get(self, request):
        return self.success({"legacy": True})


urlpatterns = [
    path("api/admin/learning/test", EchoView.as_view()),
    path("api/test-failure", FailureView.as_view()),
    path("api/admin/legacy-test", LegacyView.as_view()),
]


@override_settings(ROOT_URLCONF=__name__)
class ContractAPITests(APITestCase):
    url = "/api/admin/learning/test"

    def test_anonymous_is_real_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"], "KNOWLEDGE_AUTH_REQUIRED")
        self.assertEqual(response["X-API-Version"], "0.9.9")
        self.assertEqual(response["X-Request-ID"], response.data["request_id"])

    def test_authenticated_non_admin_reaches_new_view_but_not_legacy(self):
        user = self.create_user("student", "password")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["user_id"], user.id)
        old = self.client.get("/api/admin/legacy-test")
        self.assertEqual(old.status_code, 200)
        self.assertEqual(old.data["error"], "login-required")
        self.assertNotIn("X-API-Version", old)

    def test_appkey_alone_cannot_authenticate(self):
        user = self.create_super_admin(login=False)
        user.open_api = True
        user.open_api_appkey = "test-app-key"
        user.save()
        response = self.client.get(self.url, HTTP_APPKEY="test-app-key")
        self.assertEqual(response.status_code, 401)

    def test_appkey_cannot_replace_session_user(self):
        user = self.create_user("student", "password")
        admin = self.create_super_admin(login=False)
        admin.open_api = True
        admin.open_api_appkey = "test-app-key"
        admin.save()
        response = self.client.get(self.url, HTTP_APPKEY="test-app-key")
        self.assertEqual(response.data["data"]["user_id"], user.id)

    def test_disabled_account_rejected_after_login(self):
        user = self.create_user("student", "password")
        user.is_disabled = True
        user.save()
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_csrf_enforced_even_with_appkey(self):
        user = self.create_super_admin(login=False)
        user.open_api = True
        user.open_api_appkey = "test-app-key"
        user.save()
        client = APIClient(enforce_csrf_checks=True)
        client.login(username="root", password="root")
        response = client.post(self.url, {"value": "valid"}, format="json", HTTP_APPKEY="test-app-key")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"], "KNOWLEDGE_PERMISSION_DENIED")
        token = "a" * 32
        client.cookies["csrftoken"] = token
        response = client.post(self.url, {"value": "valid"}, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)

    def test_null_unknown_and_malformed_json_rejected(self):
        self.create_super_admin()
        for data in [None, [], {"value": None}, {"value": "ok", "unexpected": True}]:
            response = self.client.generic("POST", self.url, __import__("json").dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 400, data)
        response = self.client.generic("POST", self.url, "{broken", content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_204_has_no_body_and_retains_headers(self):
        self.create_super_admin()
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["X-API-Version"], "0.9.9")

    def test_unexpected_errors_are_sanitized_in_response_and_log(self):
        self.create_super_admin()
        with self.assertLogs("utils.contract_api", level="ERROR") as logs:
            response = self.client.get("/api/test-failure")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("provider credential", response.content.decode())
        self.assertNotIn("provider credential", "".join(logs.output))
        self.assertIn(response.data["request_id"], "".join(logs.output))

    def test_domain_error_keeps_http_status(self):
        self.create_super_admin()
        response = self.client.post("/api/test-failure", {}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.data["data"]["retryable"])

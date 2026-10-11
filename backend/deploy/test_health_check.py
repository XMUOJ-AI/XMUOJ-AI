import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import health_check


class HealthCheckTests(unittest.TestCase):
    def setUp(self):
        self.proxy_patch = patch.object(health_check.xmlrpc.client, "ServerProxy")
        self.proxy = self.proxy_patch.start()
        self.addCleanup(self.proxy_patch.stop)
        self.proxy.return_value.__enter__.return_value.supervisor.getAllProcessInfo.return_value = [{"state": 20}]
        self.opener_patch = patch.object(health_check.urllib.request, "build_opener")
        self.opener = self.opener_patch.start()
        self.addCleanup(self.opener_patch.stop)
        self.response = MagicMock()
        self.response.status = 200
        self.response.read.return_value = json.dumps({"error": None, "data": {"website_name": "Audit"}}).encode()
        self.opener.return_value.open.return_value.__enter__.return_value = self.response

    def test_running_processes_and_valid_http_response_are_healthy(self):
        self.assertIsNone(health_check.check_health())
        self.opener.return_value.open.assert_called_once_with("http://127.0.0.1:8080/api/website", timeout=3)
        self.assertEqual(self.opener.call_args.args[0].proxies, {})

    def test_running_processes_but_unreachable_http_are_unhealthy(self):
        self.opener.return_value.open.side_effect = URLError("private diagnostic detail")
        self.assertEqual(health_check.check_health(), "Application HTTP probe failed")

    def test_running_processes_but_http_timeout_are_unhealthy(self):
        self.opener.return_value.open.side_effect = TimeoutError("private diagnostic detail")
        self.assertEqual(health_check.check_health(), "Application HTTP probe failed")

    def test_unexpected_http_status_is_unhealthy(self):
        self.response.status = 503
        self.assertEqual(health_check.check_health(), "Application returned an unexpected HTTP status")

    def test_invalid_http_body_is_unhealthy_without_echoing_body(self):
        self.response.read.return_value = b"private diagnostic detail"
        self.assertEqual(health_check.check_health(), "Application HTTP probe failed")

    def test_application_error_response_is_unhealthy(self):
        self.response.read.return_value = json.dumps({"error": "database-error", "data": "private detail"}).encode()
        self.assertEqual(health_check.check_health(), "Application returned an invalid health response")

    def test_stopped_supervisor_process_does_not_probe_http(self):
        self.proxy.return_value.__enter__.return_value.supervisor.getAllProcessInfo.return_value = [{"state": 100}]
        self.assertEqual(health_check.check_health(), "Supervisor process is not running")
        self.opener.assert_not_called()

    def test_unreachable_supervisor_is_unhealthy(self):
        self.proxy.return_value.__enter__.side_effect = OSError("private detail")
        self.assertEqual(health_check.check_health(), "Supervisor probe failed")
        self.opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()

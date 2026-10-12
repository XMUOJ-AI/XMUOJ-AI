import logging
from unittest import TestCase
from unittest.mock import patch

import sentry_sdk
from sentry_sdk.transport import Transport

from oj.error_reporting import init_sentry


class SentryPrivacyTests(TestCase):
    def test_actual_sdk_envelopes_only_contain_minimal_diagnostics(self):
        class MemoryTransport(Transport):
            def __init__(self):
                super().__init__()
                self.envelopes = []

            def capture_envelope(self, envelope):
                self.envelopes.append(envelope)

        transport = MemoryTransport()
        previous_client = sentry_sdk.get_client()
        self.addCleanup(sentry_sdk.get_global_scope().set_client, previous_client)
        logger = logging.getLogger("oj.sentry-regression")
        private = "synthetic-private-cookie-token-code-exception"
        event = {
            "level": "error", "logger": logger.name,
            "message": private, "logentry": {"message": private, "params": [private]},
            "exception": {"values": [{"type": "RuntimeError", "value": private,
                                      "stacktrace": {"frames": [{"vars": {"password": private}, "context_line": private}]}}]},
            "request": {"headers": {"Cookie": private, "Authorization": private}, "data": private, "query_string": private},
            "user": {"email": private}, "extra": {"code": private}, "tags": {"token": private},
            "contexts": {"private": {"value": private}}, "breadcrumbs": {"values": [{"message": private}]},
            "transaction": private,
        }
        with patch("socket.socket.connect", side_effect=AssertionError("Network access forbidden")) as network, \
                patch("sentry_sdk.client.make_transport", return_value=transport), \
                patch.object(logger, "handlers", [logging.NullHandler()]), patch.object(logger, "propagate", False):
            init_sentry("https://synthetic@example.invalid/1")
            self.addCleanup(sentry_sdk.get_client().close)
            with sentry_sdk.new_scope() as scope:
                scope.add_attachment(bytes=private.encode(), filename="private-source.txt")
                sentry_sdk.capture_event(event)
                try:
                    raise RuntimeError(private)
                except RuntimeError as error:
                    sentry_sdk.capture_exception(error)
                    logger.exception(private, extra={"private_code": private})
            self.assertEqual(len(transport.envelopes), 3)
            for envelope in transport.envelopes:
                self.assertEqual([item.headers["type"] for item in envelope.items], ["event"])
                self.assertNotIn(private.encode(), envelope.serialize())
                payload = envelope.items[0].payload.json
                self.assertLessEqual(set(payload), {"event_id", "timestamp", "level", "logger", "platform", "logentry", "exception"})
                self.assertEqual(payload["exception"]["values"], [{"type": "RuntimeError"}])
                self.assertEqual(payload["logentry"], {"message": "Application error"})
            self.assertEqual(transport.envelopes[-1].items[0].payload.json["logger"], logger.name)
            network.assert_not_called()

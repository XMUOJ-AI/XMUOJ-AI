from unittest import TestCase
from unittest.mock import patch

import django_dramatiq
from django_dramatiq.apps import DjangoDramatiqConfig
from dramatiq.results import Results

from oj import settings as project_settings


class DramatiqRedisConfigTests(TestCase):
    def test_loaded_broker_and_result_connections_have_timeouts(self):
        with patch("django_dramatiq.apps.settings", project_settings), \
                patch("django_dramatiq.apps.dramatiq.set_broker") as installed, \
                patch("django_dramatiq.apps.dramatiq.set_encoder"), \
                patch("socket.socket.connect", side_effect=AssertionError("Network access forbidden")) as network, \
                patch("django.db.backends.base.base.BaseDatabaseWrapper.connect",
                      side_effect=AssertionError("Database access forbidden")) as database:
            DjangoDramatiqConfig("django_dramatiq", django_dramatiq)
            broker = installed.call_args.args[0]
            clients = [("broker", broker.client)] + [
                ("results", middleware.backend.client) for middleware in broker.middleware
                if isinstance(middleware, Results)
            ]
            self.assertEqual(len(clients), 2)
            for name, client in clients:
                with self.subTest(backend=name):
                    connection = client.connection_pool.make_connection()
                    self.assertEqual(connection.socket_connect_timeout, 2)
                    self.assertEqual(connection.socket_timeout, 5)
                    self.assertEqual(connection.db, 4)
                    self.assertIsNone(connection._sock)
            network.assert_not_called()
            database.assert_not_called()

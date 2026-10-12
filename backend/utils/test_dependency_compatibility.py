from unittest.mock import patch

from django.db import ProgrammingError
from django.db.backends.postgresql.base import DatabaseWrapper
from django.test import SimpleTestCase


class DatabaseReconnectSafetyTests(SimpleTestCase):
    def test_closed_atomic_transaction_cannot_silently_reconnect(self):
        connection = DatabaseWrapper({}, alias="compatibility_probe")
        connection.in_atomic_block = True
        connection.closed_in_transaction = True
        with patch.object(connection, "connect") as connect:
            with self.assertRaises(ProgrammingError):
                connection.ensure_connection()
        connect.assert_not_called()

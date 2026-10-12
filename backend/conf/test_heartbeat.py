import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import mock

from django.db import IntegrityError, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.query import QuerySet
from django.test import RequestFactory, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from judge.dispatcher import ChooseJudgeServer
from options.options import SysOptions
from .models import JudgeServer
from .views import JudgeServerHeartbeatAPI


def server_fields(hostname="heartbeat-concurrent"):
    return {"hostname": hostname, "judger_version": "1.0", "cpu_core": 2,
            "memory_usage": 12.0, "cpu_usage": 15.0, "last_heartbeat": timezone.now(),
            "service_url": "http://judge.invalid", "ip": "127.0.0.1"}


@skipUnlessDBFeature("has_select_for_update")
class ConcurrentHeartbeatTests(TransactionTestCase):
    def setUp(self):
        SysOptions.judge_server_token = "heartbeat-test-token"
        self.token = hashlib.sha256(b"heartbeat-test-token").hexdigest()
        self.pending = mock.patch("conf.views.process_pending_task")
        self.pending.start()
        self.addCleanup(self.pending.stop)

    def heartbeat(self, hostname="heartbeat-concurrent"):
        data = {"hostname": hostname, "judger_version": "2.0", "cpu_core": 2,
                "cpu": 25, "memory": 30, "action": "heartbeat", "service_url": "http://judge.invalid"}
        request = RequestFactory().post("/api/judge_server_heartbeat", json.dumps(data),
                                        content_type="application/json", HTTP_X_JUDGE_SERVER_TOKEN=self.token)
        request.ip = "127.0.0.1"
        response = JudgeServerHeartbeatAPI.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["error"], response.data)

    def test_simultaneous_first_heartbeats_create_one_server(self):
        barrier = Barrier(2)
        original_get = QuerySet.get

        def synchronized_get(queryset, *args, **kwargs):
            try:
                return original_get(queryset, *args, **kwargs)
            except JudgeServer.DoesNotExist:
                if queryset.model is JudgeServer:
                    barrier.wait(timeout=10)
                raise

        def worker():
            connections.close_all()
            try:
                self.heartbeat()
            finally:
                connections.close_all()

        with mock.patch.object(QuerySet, "get", synchronized_get), ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(JudgeServer.objects.count(), 1)
        self.heartbeat()

    def test_heartbeat_preserves_occupied_slot_primary_key_and_disabled_flag(self):
        server = JudgeServer.objects.create(**server_fields())
        with ChooseJudgeServer() as selected:
            self.assertEqual(selected.pk, server.pk)
            JudgeServer.objects.filter(pk=server.pk).update(is_disabled=True)
            self.heartbeat()
            server.refresh_from_db()
            self.assertEqual(server.task_number, 1)
            self.assertTrue(server.is_disabled)
            self.assertEqual(server.cpu_usage, 25)
            self.assertEqual(server.judger_version, "2.0")
        server.refresh_from_db()
        self.assertEqual(server.task_number, 0)
        self.assertEqual(JudgeServer.objects.count(), 1)

    def test_database_enforces_hostname_uniqueness(self):
        JudgeServer.objects.create(**server_fields())
        with self.assertRaises(IntegrityError), transaction.atomic():
            JudgeServer.objects.create(**server_fields())


class HeartbeatUniquenessMigrationTests(TransactionTestCase):
    old = [("conf", "0004_auto_20180501_0436")]
    new = [("conf", "0005_judgeserver_hostname_unique")]

    def setUp(self):
        executor = MigrationExecutor(connections["default"])
        executor.migrate(self.old)
        self.old_model = executor.loader.project_state(self.old).apps.get_model("conf", "JudgeServer")

    def tearDown(self):
        self.old_model.objects.all().delete()
        MigrationExecutor(connections["default"]).migrate(self.new)
        super().tearDown()

    def migrate(self):
        MigrationExecutor(connections["default"]).migrate(self.new)

    def test_idle_duplicates_keep_latest_telemetry_and_any_disable(self):
        first = self.old_model.objects.create(**server_fields(), is_disabled=True)
        fields = server_fields()
        fields.update(last_heartbeat=timezone.now() + timedelta(seconds=1), cpu_usage=77,
                      judger_version="3.0", cpu_core=4, memory_usage=60, ip="127.0.0.2",
                      service_url="http://new-judge.invalid")
        latest = self.old_model.objects.create(**fields)
        self.migrate()
        server = JudgeServer.objects.get(hostname=latest.hostname)
        self.assertEqual(server.pk, first.pk)
        self.assertNotEqual(server.pk, latest.pk)
        for name, value in fields.items():
            self.assertEqual(getattr(server, name), value)
        self.assertEqual(server.create_time, first.create_time)
        self.assertTrue(server.is_disabled)
        self.assertEqual(server.task_number, 0)
        self.assertEqual(JudgeServer.objects.count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            JudgeServer.objects.create(**server_fields())

    def test_nonzero_duplicate_slots_abort_without_changing_any_rows(self):
        for occupied_counts in ((1, 0), (-1, 0), (1, -1)):
            with self.subTest(occupied_counts=occupied_counts):
                self.old_model.objects.all().delete()
                for hostname, counts in (("idle", (0, 0)), ("occupied", occupied_counts)):
                    for task_number in counts:
                        self.old_model.objects.create(**server_fields(hostname), task_number=task_number)
                before = list(self.old_model.objects.order_by("pk").values())
                with self.assertRaisesRegex(RuntimeError, "nonzero task_number"):
                    self.migrate()
                self.assertEqual(list(self.old_model.objects.order_by("pk").values()), before)
                self.assertNotIn(self.new[0], MigrationExecutor(connections["default"]).loader.applied_migrations)

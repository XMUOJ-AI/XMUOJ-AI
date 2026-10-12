from django.db import migrations, models
from django.db.models import Count


def merge_idle_duplicates(apps, schema_editor):
    server_model = apps.get_model("conf", "JudgeServer")
    servers = server_model.objects.using(schema_editor.connection.alias)
    # Serialize old-version heartbeats and slot allocation with inspection,
    # cleanup and the unique constraint, in the same migration transaction.
    schema_editor.execute("LOCK TABLE %s IN ACCESS EXCLUSIVE MODE" % schema_editor.quote_name(server_model._meta.db_table))
    hostnames = list(servers.values("hostname").annotate(count=Count("pk"))
                     .filter(count__gt=1).values_list("hostname", flat=True))
    if servers.filter(hostname__in=hostnames).exclude(task_number=0).exists():
        # Workers release their original row's primary key. Summing counters and
        # deleting that row would lose releases and strand the surviving slots.
        raise RuntimeError("Cannot merge duplicate JudgeServer hostnames with nonzero task_number. "
                           "Stop heartbeats and new dispatch, let workers finish, verify slot counts, then retry migration.")
    fields = ("judger_version", "cpu_core", "memory_usage", "cpu_usage", "ip", "service_url", "last_heartbeat")
    for hostname in hostnames:
        rows = list(servers.filter(hostname=hostname).order_by("pk"))
        latest = max(rows, key=lambda row: (row.last_heartbeat, row.pk))
        values = {field: getattr(latest, field) for field in fields}
        values["is_disabled"] = any(row.is_disabled for row in rows)
        servers.filter(pk=rows[0].pk).update(**values)
        servers.filter(pk__in=[row.pk for row in rows[1:]]).delete()


class Migration(migrations.Migration):
    dependencies = [("conf", "0004_auto_20180501_0436")]
    operations = [
        # Reversing drops uniqueness but cannot reconstruct merged idle metadata.
        migrations.RunPython(merge_idle_duplicates, migrations.RunPython.noop),
        migrations.AlterField(model_name="judgeserver", name="hostname", field=models.TextField(unique=True)),
    ]

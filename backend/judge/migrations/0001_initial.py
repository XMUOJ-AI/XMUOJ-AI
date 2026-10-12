from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("submission", "0013_reconcile_existing_models")]

    operations = [
        migrations.CreateModel(
            name="JudgeDispatch",
            fields=[
                ("submission", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True,
                                                   related_name="judge_dispatch", serialize=False, to="submission.submission")),
                ("status", models.CharField(db_index=True, default="queued", max_length=16)),
                ("delivered_time", models.DateTimeField(null=True)),
                ("updated_time", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "judge_dispatch"},
        ),
        migrations.AddConstraint(model_name="judgedispatch", constraint=models.CheckConstraint(
            check=models.Q(status__in=("queued", "running", "failed", "done")), name="judge_dispatch_status")),
    ]


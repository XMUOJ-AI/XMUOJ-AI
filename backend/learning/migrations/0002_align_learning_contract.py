from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("learning", "0001_initial")]
    operations = [
        migrations.RemoveConstraint(model_name="problemknowledgerating", name="pkr_counts_valid"),
        migrations.RenameField(model_name="problemknowledgerating", old_name="sample_count", new_name="attempt_count"),
        migrations.AddConstraint(model_name="problemknowledgerating", constraint=models.CheckConstraint(
            check=models.Q(accepted_count__lte=models.F("attempt_count")), name="pkr_counts_valid")),
        migrations.AlterField(model_name="teachingclass", name="term", field=models.CharField(default="", max_length=32)),
        migrations.AlterField(model_name="teachingclass", name="status", field=models.CharField(default="active", max_length=16)),
    ]

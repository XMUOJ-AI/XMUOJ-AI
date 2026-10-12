from django.db import models
from django.db.models import Q


class JudgeDispatch(models.Model):
    submission = models.OneToOneField("submission.Submission", primary_key=True, on_delete=models.CASCADE, related_name="judge_dispatch")
    status = models.CharField(max_length=16, default="queued", db_index=True)
    delivered_time = models.DateTimeField(null=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "judge_dispatch"
        constraints = [models.CheckConstraint(check=Q(status__in=("queued", "running", "failed", "done")), name="judge_dispatch_status")]

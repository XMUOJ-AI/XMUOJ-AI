"""Submission outbox; broker delivery is at least once, verdict application is serialized."""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from account.models import User
from submission.models import JudgeStatus, Submission
from .models import JudgeDispatch

logger = logging.getLogger(__name__)


@transaction.atomic
def request_judge(submission):
    JudgeDispatch.objects.update_or_create(submission=submission, defaults={"status": "queued", "delivered_time": None})
    transaction.on_commit(lambda: deliver_judge(submission.pk))


def set_dispatch_status(submission_id, status):
    values = {"status": status, "updated_time": timezone.now()}
    if status == "queued":
        values["delivered_time"] = None
    JudgeDispatch.objects.filter(submission_id=submission_id).update(**values)


def deliver_judge(submission_id):
    from .tasks import judge_task
    try:
        with transaction.atomic():
            dispatch = JudgeDispatch.objects.select_for_update(of=("self",)).select_related("submission").filter(submission_id=submission_id, status="queued").first()
            if not dispatch or (dispatch.delivered_time and dispatch.delivered_time > timezone.now() - timedelta(seconds=60)):
                return False
            if not User.objects.filter(pk=dispatch.submission.user_id, is_disabled=False).exists():
                set_dispatch_status(submission_id, "failed")
                return False
            judge_task.send(dispatch.submission_id, dispatch.submission.problem_id)
            dispatch.delivered_time = timezone.now()
            dispatch.save(update_fields=["delivered_time", "updated_time"])
            return True
    except Exception as exc:
        logger.warning("judge_enqueue_failed submission=%s type=%s", submission_id, type(exc).__name__)
        return False


def dispatch_pending(limit=100):
    keys = list(JudgeDispatch.objects.filter(status="queued").filter(
        Q(delivered_time__isnull=True) | Q(delivered_time__lte=timezone.now() - timedelta(seconds=60)))
        .order_by("updated_time", "submission_id").values_list("submission_id", flat=True)[:limit])
    return sum(deliver_judge(key) for key in keys)


def recover_dispatches(limit=100):
    from .dispatcher import submission_worker_lock, sync_judge_server_tasks
    # Backfill legacy waiting submissions, but leave pre-upgrade JUDGING failures for explicit operator recovery.
    missing = Submission.objects.filter(judge_dispatch__isnull=True, user_id__in=User.objects.filter(is_disabled=False).values("pk")).filter(
        Q(result=JudgeStatus.PENDING) | Q(statistic_info___rejudge_pending=True)).order_by("create_time", "pk")[:limit]
    JudgeDispatch.objects.bulk_create([JudgeDispatch(submission=submission) for submission in missing], ignore_conflicts=True)
    keys = list(JudgeDispatch.objects.filter(status="running").order_by("updated_time").values_list("submission_id", flat=True)[:limit])
    for key in keys:
        with submission_worker_lock(key) as acquired:
            if not acquired:
                continue
            with transaction.atomic():
                dispatch = JudgeDispatch.objects.select_for_update(of=("self",)).select_related("submission").get(submission_id=key)
                if dispatch.status != "running":
                    continue
                submission = dispatch.submission
                pending = submission.result in (JudgeStatus.PENDING, JudgeStatus.JUDGING) or submission.statistic_info.get("_rejudge_pending")
                set_dispatch_status(key, "queued" if pending else "done")
    sync_judge_server_tasks()
    return dispatch_pending(limit)

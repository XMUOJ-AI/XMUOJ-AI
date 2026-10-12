import logging

from django.db import OperationalError
from django.db.models.signals import post_save
from django.dispatch import receiver
from submission.models import Submission
from utils.contract_api import ContractError


class LearningCaptureError(RuntimeError):
    def __init__(self, retryable=False):
        self.retryable = retryable
        super().__init__("LEARNING_CAPTURE_FAILED")


@receiver(post_save, sender=Submission, dispatch_uid="learning_submission_outbox")
def submission_completed(sender, instance, raw=False, update_fields=None, **kwargs):
    if raw or (update_fields is not None and not {"result", "statistic_info"}.intersection(update_fields)):
        return
    from .ratings import capture_submission
    try:
        capture_submission(instance)
    except Exception as exc:
        # Never acknowledge a verdict whose immutable learning snapshot was lost.
        # Submission.save() rolls the verdict back; judge workers retry transient failures.
        logging.getLogger(__name__).error("learning_capture_failed submission=%s type=%s", instance.pk, type(exc).__name__)
        retryable = isinstance(exc, OperationalError) or isinstance(exc, ContractError) and exc.retryable
        raise LearningCaptureError(retryable=retryable) from None

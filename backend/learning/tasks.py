import dramatiq
from django.db.models import F
from .models import LearningSubmissionEvent
from .ratings import process_event


@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000, time_limit=120000)
def process_learning_event(event_id):
    revision = LearningSubmissionEvent.objects.filter(pk=event_id).values_list("revision", flat=True).first()
    try:
        process_event(event_id)
    except Exception:
        LearningSubmissionEvent.objects.filter(pk=event_id, revision=revision).exclude(
            status="processed", processed_revision=F("revision")).update(status="failed", error_code="LEARNING_PROCESSING_FAILED")
        raise RuntimeError("LEARNING_PROCESSING_FAILED") from None

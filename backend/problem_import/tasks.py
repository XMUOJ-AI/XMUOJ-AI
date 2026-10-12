import dramatiq

from .services import commit_batch, recover_batches, validate_batch


@dramatiq.actor(queue_name="problem_import", max_retries=3, min_backoff=5000, time_limit=1800000)
def validate_import_batch(batch_id):
    validate_batch(batch_id)


@dramatiq.actor(queue_name="problem_import", max_retries=3, min_backoff=5000, time_limit=1800000)
def commit_import_batch(batch_id):
    commit_batch(batch_id)


@dramatiq.actor(queue_name="problem_import", max_retries=3, time_limit=1800000)
def recover_import_batches(age_seconds=3600):
    recover_batches(age_seconds)

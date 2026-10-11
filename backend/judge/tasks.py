import dramatiq

from account.models import User
from submission.models import Submission
from judge.dispatcher import JudgeDispatcher
from learning.signals import LearningCaptureError
from utils.shortcuts import DRAMATIQ_WORKER_ARGS


def retry_learning_capture(retries, exception):
    # retry_when overrides Dramatiq's max_retries check, so bound it here too.
    return retries < 3 and isinstance(exception, LearningCaptureError) and exception.retryable


@dramatiq.actor(**DRAMATIQ_WORKER_ARGS(max_retries=3), retry_when=retry_learning_capture,
                min_backoff=1000, max_backoff=10000)
def judge_task(submission_id, problem_id):
    uid = Submission.objects.get(id=submission_id).user_id
    if User.objects.get(id=uid).is_disabled:
        return
    JudgeDispatcher(submission_id, problem_id).judge()

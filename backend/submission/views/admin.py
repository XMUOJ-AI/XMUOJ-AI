from django.db import transaction

from judge.dispatcher import submission_worker_lock
from judge.services import request_judge
# from judge.dispatcher import JudgeDispatcher
from utils.api import APIView
from ..models import JudgeStatus, Submission


class SubmissionRejudgeAPI(APIView):
    def post(self, request):
        if not isinstance(request.data, dict) or set(request.data) != {"id"}:
            return self.error("Parameter error, id is required")
        id = request.data.get("id")
        if not isinstance(id, str) or not 1 <= len(id) <= 128:
            return self.error("Parameter error, id is required")
        try:
            submission = Submission.objects.select_related("problem", "contest").get(id=id)
        except Submission.DoesNotExist:
            return self.error("Submission does not exists")

        if submission.contest_id:
            if not request.user.is_contest_admin(submission.contest):
                return self.error("Permission denied")
        elif not request.user.is_super_admin():
            return self.error("Permission denied")

        with submission_worker_lock(submission.pk) as acquired, transaction.atomic():
            if not acquired:
                return self.error("Submission is already being judged")
            submission = Submission.objects.select_for_update().get(pk=submission.pk)
            if submission.result == JudgeStatus.JUDGING:
                return self.error("Submission is already being judged")
            # Preserve the authoritative score until the worker enters JUDGING.
            # Clearing a terminal OI score here emits a false zero-score event.
            submission.statistic_info = dict(submission.statistic_info or {}, _rejudge_pending=True)
            submission.save(update_fields=["statistic_info"])
            request_judge(submission)
        return self.success()

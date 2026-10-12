from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from account.models import User
from judge.dispatcher import submission_worker_lock
from judge.services import request_judge
from submission.models import JudgeStatus, Submission


class Command(BaseCommand):
    help = "Explicitly requeue one stuck JUDGING submission after correcting the failure that exhausted retries."

    def add_arguments(self, parser):
        parser.add_argument("submission_id")

    def handle(self, *args, **options):
        with submission_worker_lock(options["submission_id"]) as acquired, transaction.atomic():
            if not acquired:
                raise CommandError("Submission still has an active judge worker")
            submission = Submission.objects.select_for_update().filter(pk=options["submission_id"]).first()
            if submission is None or submission.result != JudgeStatus.JUDGING:
                raise CommandError("A JUDGING submission is required; completed verdicts are not reset")
            if not User.objects.filter(pk=submission.user_id, is_disabled=False).exists():
                raise CommandError("Submission owner is unavailable or disabled")
            request_judge(submission)
        self.stdout.write(f"Queued durable recovery for judging submission {submission.pk}")

from django.core.management.base import BaseCommand, CommandError

from account.models import User
from judge.tasks import judge_task
from submission.models import JudgeStatus, Submission


class Command(BaseCommand):
    help = "Explicitly requeue one stuck JUDGING submission after correcting the failure that exhausted retries."

    def add_arguments(self, parser):
        parser.add_argument("submission_id")

    def handle(self, *args, **options):
        submission = Submission.objects.filter(pk=options["submission_id"]).first()
        if submission is None or submission.result != JudgeStatus.JUDGING:
            raise CommandError("A JUDGING submission is required; completed verdicts are not reset")
        if not User.objects.filter(pk=submission.user_id, is_disabled=False).exists():
            raise CommandError("Submission owner is unavailable or disabled")
        judge_task.send(submission.pk, submission.problem_id)
        self.stdout.write(f"Requeued judging submission {submission.pk}")

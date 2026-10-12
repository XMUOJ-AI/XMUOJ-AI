from django.core.management.base import BaseCommand, CommandError

from contest.models import Contest
from contest.scoring import rebuild_contest_scores


class Command(BaseCommand):
    help = "Rebuild one contest's ranks, problem statistics and participation from eligible durable submissions."

    def add_arguments(self, parser):
        parser.add_argument("contest_id", type=int)

    def handle(self, *args, **options):
        try:
            count = rebuild_contest_scores(options["contest_id"])
        except Contest.DoesNotExist:
            raise CommandError("Contest does not exist") from None
        self.stdout.write(f"Rebuilt contest {options['contest_id']} from {count} eligible submissions")

from django.core.management.base import BaseCommand, CommandError

from problem_import.services import recover_batches


class Command(BaseCommand):
    help = "Recover stale imports without overwriting source bindings or deleting referenced testcase files."

    def add_arguments(self, parser):
        parser.add_argument("--age-seconds", type=int, default=3600)

    def handle(self, *args, **options):
        if options["age_seconds"] < 0:
            raise CommandError("--age-seconds must be nonnegative", returncode=2)
        self.stdout.write(str(recover_batches(options["age_seconds"])))

from django.core.management.base import BaseCommand

from judge.services import recover_dispatches


class Command(BaseCommand):
    help = "Recover lost judge deliveries and interrupted workers from the durable outbox."

    def handle(self, *args, **options):
        count = recover_dispatches()
        self.stdout.write(f"Dispatched {count} judge tasks")

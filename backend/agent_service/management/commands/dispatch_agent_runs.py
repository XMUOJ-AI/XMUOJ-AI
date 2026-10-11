from django.core.management.base import BaseCommand
from agent_service.runtime import recover_runs


class Command(BaseCommand):
    help = "Recover interrupted Agent runs and deliver durable queue intents (repeat from scheduler)."

    def handle(self, **options):
        self.stdout.write(str(recover_runs()) + " queue intents delivered")

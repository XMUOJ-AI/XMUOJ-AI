"""Small supervisor entry point for independently recoverable durable workflows."""
import logging
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run one workflow recovery pass, or poll under a process supervisor."

    def add_arguments(self, parser):
        parser.add_argument("workflow", choices=("learning", "agent", "import", "credentials"))
        parser.add_argument("--interval", type=int, default=0)

    def handle(self, *args, **options):
        interval = options["interval"]
        if interval != 0 and interval < 10:
            raise CommandError("interval must be zero (one pass) or at least 10 seconds")
        while True:
            close_old_connections()
            try:
                if options["workflow"] == "learning":
                    call_command("recover_learning", backfill=True, limit=1000)
                elif options["workflow"] == "agent":
                    call_command("dispatch_agent_runs")
                elif options["workflow"] == "credentials":
                    call_command("cleanup_user_credentials")
                else:
                    call_command("recover_problem_imports")
            except Exception as exc:
                logger.error("workflow_recovery_failed workflow=%s type=%s", options["workflow"], type(exc).__name__)
                if not interval:
                    raise CommandError("Workflow recovery failed; retry when dependencies are available") from None
            finally:
                close_old_connections()
            if not interval:
                return
            time.sleep(interval)

from django.core.management.base import BaseCommand

from account.credential_exports import cleanup_expired_exports


class Command(BaseCommand):
    help = "Remove expired credential exports and abandoned private files (run at least every minute)."

    def handle(self, *args, **options):
        deleted = cleanup_expired_exports()
        self.stdout.write(f"Removed {deleted} expired credential export receipts")

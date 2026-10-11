import json
import uuid
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from account.models import User
from problem_import.services import batch_data, commit_batch, receive_archive, report, request_commit, validate_batch
from utils.contract_api import ContractError


class Command(BaseCommand):
    help = "Validate or commit a formal QDUOJ batch; JSONL must first be converted with the delivery builder."

    def add_arguments(self, parser):
        parser.add_argument("archive")
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--commit", action="store_true")
        parser.add_argument("--allow-partial", action="store_true")
        parser.add_argument("--batch-id")
        parser.add_argument("--report")
        parser.add_argument("--uploaded-by")
        parser.add_argument("--acknowledge-warning", action="append", default=[])

    def handle(self, *args, **options):
        path = Path(options["archive"])
        if path.is_symlink() or not path.is_file():
            raise CommandError("Archive must be a regular non-symlink ZIP file", returncode=2)
        users = User.objects.filter(is_disabled=False, admin_type__in=("Admin", "Super Admin"))
        if options["uploaded_by"]:
            users = users.filter(username=options["uploaded_by"])
        if users.count() != 1:
            raise CommandError("--uploaded-by must identify an enabled administrator", returncode=2)
        user = users.get()
        try:
            with path.open("rb") as source:
                batch, _ = receive_archive(source, user, command=True, expected_batch_id=options["batch_id"])
            if batch.status == "uploaded":
                batch = validate_batch(batch.pk)
            if options["commit"] and batch.status in ("validated", "partial", "failed"):
                data = {"allow_partial": options["allow_partial"], "problem_ids": [],
                        "acknowledged_warning_codes": sorted(set(options["acknowledge_warning"]))}
                batch, _, _ = request_commit(batch.batch_key, user, "command-" + uuid.uuid4().hex, data)
                batch = commit_batch(batch.pk)
            if options["report"]:
                Path(options["report"]).write_text(json.dumps(report(batch), ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
            self.stdout.write(json.dumps(batch_data(batch), ensure_ascii=False))
            if batch.status in ("failed", "partial") or batch.error_count:
                raise CommandError("Batch contains validation or import errors", returncode=1)
        except ContractError as error:
            raise CommandError(error.code + ": " + error.message, returncode=2 if error.code in (
                "IMPORT_UNSAFE_PATH", "IMPORT_UNSAFE_ARCHIVE", "IMPORT_ZIP_BOMB", "IMPORT_SIZE_LIMIT",
                "IMPORT_ZIP_INVALID", "IMPORT_FILE_INVALID") else 1)
        except OSError:
            raise CommandError("Cannot read archive, write report, or access import storage", returncode=2)

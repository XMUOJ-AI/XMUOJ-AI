"""Private, expiring credential files and idempotent creation receipts."""
import hashlib
import io
import json
import os
import re
import secrets
import stat
from datetime import timedelta

import xlsxwriter
from django.conf import settings
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .models import UserCredentialExport


EXPORT_LIFETIME = timedelta(hours=24)
EXPORT_ID_PATTERN = re.compile(r"[a-f0-9]{64}\Z")


def export_directory():
    path = getattr(settings, "USER_CREDENTIAL_EXPORT_DIR", os.path.join(settings.DATA_DIR, "user_credentials"))
    os.makedirs(path, mode=0o700, exist_ok=True)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise OSError("Invalid credential export directory")
    os.chmod(path, 0o700)
    return path


def export_path(file_id):
    if not EXPORT_ID_PATTERN.fullmatch(file_id):
        raise ValueError("Invalid credential export id")
    return os.path.join(export_directory(), f"{file_id}.xlsx")


def request_digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def export_metadata(export):
    return {"file_id": export.id, "created_count": export.created_count, "updated_count": export.updated_count,
            "operation": export.operation, "created_at": export.created_at.isoformat(), "expires_at": export.expires_at.isoformat()}


def remove_export_file(file_id):
    try:
        os.unlink(export_path(file_id))
    except FileNotFoundError:
        pass


def cleanup_expired_exports():
    """Also remove old orphan files left by process crashes or deleted owners."""
    current_time = timezone.now()
    expired = UserCredentialExport.objects.filter(expires_at__lte=current_time)
    for export in expired.iterator():
        remove_export_file(export.id)
    deleted, _ = expired.delete()
    cutoff = (current_time - EXPORT_LIFETIME).timestamp()
    for entry in os.scandir(export_directory()):
        if entry.name.endswith(".xlsx") and EXPORT_ID_PATTERN.fullmatch(entry.name[:-5]):
            try:
                if (entry.stat(follow_symlinks=False).st_mtime <= cutoff
                        and not UserCredentialExport.objects.filter(pk=entry.name[:-5]).exists()):
                    os.unlink(entry.path)
            except FileNotFoundError:
                pass  # Another cleanup process has already removed it.
    return deleted


@sensitive_variables()
def create_export(owner, operation, digest, credentials, updated_count=0):
    """Called inside the same database transaction as account creation."""
    content = io.BytesIO()
    # in_memory prevents xlsxwriter placing password-containing XML in system /tmp.
    with xlsxwriter.Workbook(content, {"in_memory": True}) as workbook:
        worksheet = workbook.add_worksheet()
        worksheet.set_column("A:B", 28)
        worksheet.write_row(0, 0, ["Username", "Password"])
        for row, (username, password) in enumerate(credentials, 1):
            worksheet.write_string(row, 0, username)
            worksheet.write_string(row, 1, password)
    file_id = secrets.token_hex(32)
    path = export_path(file_id)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content.getvalue())
            target.flush()
            os.fsync(target.fileno())
        return UserCredentialExport.objects.create(
            id=file_id, created_by=owner, operation=operation, request_digest=digest,
            created_count=len(credentials), updated_count=updated_count, expires_at=timezone.now() + EXPORT_LIFETIME)
    except Exception:
        remove_export_file(file_id)
        raise


def read_export(export):
    descriptor = os.open(export_path(export.id), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise OSError("Invalid credential export permissions")
        return source.read()

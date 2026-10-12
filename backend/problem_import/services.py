import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from account.models import ProblemPermission
from options.options import SysOptions
from problem.models import Problem
from problem.tag import normalize_tag_name, resolve_problem_tags
from utils.contract_api import ContractError, request_fingerprint, transaction_lock
from utils.xss_filter import XSSHtml

from .archive import Archive, COMMAND_LIMIT, WEB_LIMIT, content_hash, fail, issue, schema_errors
from .models import CollectedProblem, ExternalProblemBinding, ExternalTagMapping, ProblemImportBatch


def can_import(user):
    return user.is_authenticated and not user.is_disabled and (user.is_super_admin() or (
        user.is_admin_role() and user.problem_permission in (ProblemPermission.OWN, ProblemPermission.ALL)))


def can_access_batch(batch, user):
    return can_import(user) and (user.is_super_admin() or user.problem_permission == ProblemPermission.ALL
                                 or batch.uploaded_by_id == user.pk)


def get_batch(batch_key, user, for_update=False):
    batches = ProblemImportBatch.objects.select_for_update() if for_update else ProblemImportBatch.objects
    batch = batches.filter(batch_key=batch_key).first()
    if batch is None or not can_access_batch(batch, user):
        raise ContractError("IMPORT_NOT_FOUND", "资源不存在或无权访问", 404)
    return batch


@contextmanager
def worker_lock(batch_id):
    """Session lock excludes duplicate workers/recovery while allowing per-row commits."""
    ident = int.from_bytes(hashlib.sha256(("problem-import-worker:" + str(batch_id)).encode()).digest()[:8],
                           "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [ident])
        acquired = cursor.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [ident])


def storage_root():
    path = Path(getattr(settings, "PROBLEM_IMPORT_DIR", Path(settings.DATA_DIR) / "config" / "problem_import"))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def receive_archive(stream, user, command=False, expected_batch_id=None):
    if not can_import(user):
        raise ContractError("IMPORT_PERMISSION_DENIED", "没有此操作权限", 403)
    limit = COMMAND_LIMIT if command else WEB_LIMIT
    digest, size = hashlib.sha256(), 0
    descriptor, name = tempfile.mkstemp(suffix=".zip", dir=storage_root())
    try:
        with os.fdopen(descriptor, "wb") as target:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise ContractError("IMPORT_SIZE_LIMIT", "ZIP 超过入口大小限制", 413)
                target.write(chunk)
                digest.update(chunk)
            target.flush()
            os.fsync(target.fileno())
        with Archive(name, command=command) as archive:
            manifest = archive.manifest
        if expected_batch_id and manifest["batch_id"] != expected_batch_id:
            fail("BATCH_CONFLICT", "--batch-id 与 manifest.batch_id 不一致")
        with transaction.atomic():
            transaction_lock("problem_import", "upload")
            existing = ProblemImportBatch.objects.select_for_update().filter(archive_sha256=digest.hexdigest()).first()
            if existing:
                if can_access_batch(existing, user):
                    return existing, False
            if existing or ProblemImportBatch.objects.filter(batch_key=manifest["batch_id"]).exists():
                raise ContractError("IMPORT_BATCH_CONFLICT", "数据包或批次标识已存在", 409)
            batch = ProblemImportBatch.objects.create(
                batch_key=manifest["batch_id"], producer=manifest["producer"]["name"],
                source_platforms=manifest["source_platforms"], manifest=manifest,
                archive_sha256=digest.hexdigest(), archive_path=name, uploaded_by=user,
                problem_count=manifest["problem_count"], command_limits=command,
            )
        name = None
        return batch, True
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def summary(batch):
    return {"total": batch.problem_count, "valid": batch.valid_count, "warnings": batch.warning_count,
            "errors": batch.error_count, "duplicates": batch.problems.filter(import_status="duplicate").count(),
            "imported": batch.imported_count, "skipped": batch.skipped_count}


def batch_data(batch):
    return {"batch_id": batch.batch_key, "schema_version": batch.schema_version, "status": batch.status,
            "archive_sha256": batch.archive_sha256, "summary": summary(batch),
            "created_time": batch.created_time.isoformat(),
            "validated_time": batch.validated_time.isoformat() if batch.validated_time else None,
            "committed_time": batch.committed_time.isoformat() if batch.committed_time else None}


def recalculate(batch):
    rows = list(batch.problems.only("import_status", "validation_errors"))
    issues = batch.issues + [value for row in rows for value in row.validation_errors]
    batch.valid_count = sum(row.import_status in ("ready", "duplicate", "importing", "imported", "skipped")
                            and not any(i["level"] in ("error", "fatal") for i in row.validation_errors) for row in rows)
    batch.warning_count = sum(value["level"] == "warning" for value in issues)
    batch.error_count = sum(value["level"] in ("error", "fatal") for value in issues)
    batch.imported_count = sum(row.import_status == "imported" for row in rows)
    batch.skipped_count = sum(row.import_status in ("skipped", "duplicate") for row in rows)
    batch.error_summary = dict(Counter(value["code"] for value in issues))
    batch.save()


def error_issue(error, fallback="VALIDATION_FAILED"):
    if isinstance(error, ContractError):
        return {"level": "error", "code": error.code, "message": error.message,
                "field": error.details.get("field")}
    return issue(fallback, "处理失败；请检查环境和任务日志后恢复")


def resolve_tags(names):
    tags, unknown, collisions = resolve_problem_tags(names, allow_create=False)
    ambiguous = {normalize_tag_name(name) for name in names} & set(collisions)
    blocked = {ident for name in ambiguous for ident in collisions[name]}
    return [tag for tag in tags if tag.pk not in blocked], bool(unknown or ambiguous)


def record_issues(archive, record, entry):
    issues = schema_errors(record, "problem-import-v1")
    raw, value = {}, None
    if issues:
        return issues, raw, value
    if "judge_data" in record:
        issues.append(issue("DANGLING_REFERENCE", "正式 ZIP 必须使用 manifest 交付状态替代中间测试路径", "judge_data"))
    if record.get("content_hash") and record["content_hash"] != content_hash(record):
        issues.append(issue("CONTENT_HASH_MISMATCH", "规范化题面内容哈希不一致", "content_hash"))
    if record["source_platform"] not in archive.manifest["source_platforms"]:
        issues.append(issue("MANIFEST_INVALID", "来源平台未在 manifest 声明", "source_platform"))
    if not record["source_url"].startswith(("https://", "http://")):
        issues.append(issue("SOURCE_URL_INVALID", "来源地址必须为 HTTP(S)", "source_url"))
    if record.get("assets"):
        declarations = {item["path"]: item for item in archive.manifest["files"]}
        for asset in record["assets"]:
            declared = declarations.get(asset["path"])
            if not declared or any(declared[key] != asset[key] for key in ("sha256", "size_bytes", "media_type")):
                issues.append(issue("ASSET_MISMATCH", "媒体引用与 manifest 文件声明不一致", "assets"))
        issues.append(issue("ASSET_REVIEW_REQUIRED", "媒体保留于隔离数据包，待人工审核后再发布", "assets", "warning"))
    try:
        if record.get("raw_data_path"):
            path = record["raw_data_path"]
            if not path.startswith("metadata/raw/"):
                fail("DANGLING_REFERENCE", "原始快照路径必须位于 metadata/raw/", "raw_data_path")
            raw = archive.read_json(path)
        value = archive.problem(record, entry)
    except ContractError as error:
        issues.append(error_issue(error))
    _, unresolved = resolve_tags(record["tags_unified"])
    if unresolved:
        issues.append(issue("TAG_UNRESOLVED", "未知或歧义标签不会建立正式关联", "tags_unified", "warning"))
    if record["knowledge_candidates"]:
        issues.append(issue("KNOWLEDGE_CANDIDATE_INCOMPLETE", "名称候选缺少角色和权重，保留采集记录等待人工补全",
                            "knowledge_candidates", "warning"))
    if not record.get("provenance"):
        issues.append(issue("PROVENANCE_REVIEW_REQUIRED", "缺少授权说明，题目将保持不可见", "provenance", "warning"))
    if record["review_status"] != "approved":
        issues.append(issue("REVIEW_REQUIRED", "未审核内容保持不可见", "review_status", "warning"))
    if record.get("duplicate_of"):
        issues.append(issue("DUPLICATE_REVIEW_REQUIRED", "跨来源重复声明需要人工确认，当前记录不会自动导入",
                            "duplicate_of", "warning"))
    if entry["directory"] is None:
        issues.append(issue("JUDGE_DATA_NOT_READY", "题目缺少可直接判题的数据，仅保留采集记录", "judge_data", "warning"))
    for field in ("description_html", "input_description_html", "output_description_html", "hint_html"):
        with XSSHtml() as cleaner:
            if cleaner.clean(record.get(field) or "") != (record.get(field) or ""):
                issues.append(issue("HTML_SANITIZED", "题面 HTML 将通过现有安全过滤器清理", field, "warning"))
    return issues, raw, value


def validate_batch(batch_id):
    with worker_lock(batch_id) as acquired:
        if not acquired:
            return ProblemImportBatch.objects.get(pk=batch_id)
        return _validate_batch(batch_id)


def _validate_batch(batch_id):
    with transaction.atomic():
        batch = ProblemImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status not in ("uploaded", "validating"):
            return batch
        batch.status = "validating"
        batch.save()
    try:
        with transaction.atomic():
            transaction_lock("problem_import_batch", str(batch_id))
            batch = ProblemImportBatch.objects.select_for_update().get(pk=batch_id)
            if batch.status != "validating":
                return batch
            with Archive(batch.archive_path, batch.command_limits) as archive:
                verify_archive_hash(batch)
                archive.verify_files()
                records = archive.metadata()
                batch.tag_mappings = archive.mappings()
                for mapping in batch.tag_mappings:
                    existing = ExternalTagMapping.objects.filter(
                        source_platform=mapping["source_platform"],
                        normalized_source_tag=mapping["normalized_source_tag"]).first()
                    if existing and (existing.unified_tag != mapping["unified_tag"] or
                                     (existing.knowledge_point_id and existing.knowledge_point.code != mapping["knowledge_code"])):
                        batch.issues.append(issue("TAG_MAPPING_CONFLICT", "来源标签与已有映射冲突，保留原映射供人工审核",
                                                  "tag_mapping.csv", "warning"))
                for (line, original), entry in records:
                    issues, raw, value = record_issues(archive, original, entry)
                    record = original if isinstance(original, dict) else {}
                    invalid = bool(schema_errors(record, "problem-import-v1"))
                    source_platform = "invalid" if invalid else record["source_platform"]
                    source_id = f"invalid:{batch.pk}:{line}" if invalid else record["source_id"]
                    digest = "0" * 64 if invalid else content_hash(record)
                    status, bound_problem = "ready", None
                    if any(i["level"] in ("error", "fatal") for i in issues):
                        status = "failed"
                    elif entry["directory"] is None or record["review_status"] == "rejected" or record.get("duplicate_of"):
                        status = "skipped"
                    binding = ExternalProblemBinding.objects.filter(source_platform=source_platform,
                                                                    source_id=source_id).first()
                    if binding and status == "ready":
                        if binding.latest_content_hash == digest:
                            status, bound_problem = "duplicate", binding.problem
                        else:
                            status = "skipped"
                            issues.append(issue("SOURCE_UPDATED", "来源内容已变化，保留待审记录且不覆盖既有题目",
                                                "content_hash", "warning"))
                    metadata = dict(record, problem_key=entry["problem_key"])
                    CollectedProblem.objects.create(
                        batch=batch, line_number=line, source_platform=source_platform, source_id=source_id,
                        source_url=record.get("source_url", "") if not invalid else "",
                        title=(record.get("title_cn") or record.get("title", "")) if not invalid else "",
                        content_hash=digest, raw_data=raw, standardized_data=metadata, validation_errors=issues,
                        review_status=record.get("review_status", "pending") if not invalid else "pending",
                        import_status=status, imported_problem=bound_problem,
                        collected_at=parse_datetime(record["collected_at"]) if not invalid else timezone.now(),
                    )
                batch.status = "validated"
                batch.validated_time = timezone.now()
                if batch.tag_mappings:
                    batch.issues.append(issue("TAG_MAPPING_PENDING", "来源标签映射仅登记为待审候选，不自动启用",
                                              "tag_mapping.csv", "warning"))
                recalculate(batch)
        return batch
    except ContractError as error:
        with transaction.atomic():
            batch = ProblemImportBatch.objects.select_for_update().get(pk=batch_id)
            batch.status = "failed"
            batch.issues = [error_issue(error)]
            batch.validated_time = timezone.now()
            recalculate(batch)
        return batch


def verify_archive_hash(batch):
    digest = hashlib.sha256()
    with open(batch.archive_path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != batch.archive_sha256:
        fail("FILE_HASH_MISMATCH", "已保存的 ZIP 与接收时哈希不一致")


def request_commit(batch_key, user, key, data):
    fingerprint = request_fingerprint(data)
    operation_key = str(user.pk) + ":" + key
    with transaction.atomic():
        # Check the locked row before replaying an accepted operation as ownership
        # may have changed since the view's preliminary check or the first request.
        batch = get_batch(batch_key, user, for_update=True)
        previous = batch.commit_operations.get(operation_key)
        if previous:
            if previous["fingerprint"] != fingerprint:
                raise ContractError("IMPORT_IDEMPOTENCY_CONFLICT", "相同幂等键已用于不同请求", 409)
            return batch, previous["response"], batch.status == "importing"
        if batch.status not in ("validated", "partial", "failed") or not batch.validated_time or batch.issues and any(
                i["level"] in ("error", "fatal") for i in batch.issues):
            raise ContractError("IMPORT_STATE_CONFLICT", "批次尚未校验完成或存在整包错误", 409)
        retryable = list(batch.problems.filter(import_status="failed", allocated_test_case_id__isnull=False))
        retry_ids = {row.pk for row in retryable}
        if batch.problems.filter(import_status="failed", allocated_test_case_id__isnull=True).exists() and not data["allow_partial"]:
            raise ContractError("IMPORT_VALIDATION_FAILED", "存在校验错误；整批提交被拒绝", 409)
        candidates = batch.problems.defer("standardized_data", "raw_data")
        selected = list(candidates.filter(pk__in=data["problem_ids"])) if data["problem_ids"] else list(
            candidates.filter(import_status__in=("ready", "duplicate", "failed")))
        if not data["problem_ids"]:
            selected = [row for row in selected if row.import_status != "failed" or row.pk in retry_ids]
        if data["problem_ids"] and len(selected) != len(data["problem_ids"]):
            fail("PROBLEM_SELECTION_INVALID", "problem_ids 必须属于当前批次")
        if any(row.import_status not in ("ready", "duplicate") and row.pk not in retry_ids for row in selected):
            fail("PROBLEM_SELECTION_INVALID", "选择包含不可导入记录")
        warnings = {i["code"] for i in batch.issues if i["level"] == "warning"}
        warnings.update(i["code"] for row in selected for i in row.validation_errors if i["level"] == "warning")
        missing = warnings - set(data["acknowledged_warning_codes"])
        if missing:
            raise ContractError("IMPORT_WARNING_ACK_REQUIRED", "提交前必须确认警告", 409,
                                {"warning_codes": sorted(missing)})
        if not selected:
            fail("NO_READY_PROBLEMS", "批次没有可导入题目")
        batch.status = "importing"
        batch.commit_request = dict(data, selected_ids=[row.pk for row in selected], user_id=user.pk)
        if data["problem_ids"]:
            batch.problems.filter(import_status="ready").exclude(pk__in=data["problem_ids"]).update(import_status="skipped")
        for row in selected:
            # Persist ownership of paths before any filesystem mutation. The leading
            # nibble is fixed to satisfy the allocation format even for UUIDs starting 0.
            if row.import_status in ("ready", "failed"):
                if row.import_status == "failed":
                    clean_allocation(row)
                    # Keep positions (and therefore cursor issue IDs) stable and
                    # preserve failed-attempt evidence when a retry supersedes it.
                    row.validation_errors = [dict(i, level="info") if i["code"] == row.import_error_code
                                             and i["level"] == "error" else i for i in row.validation_errors]
                    row.import_error_code = row.import_error_message = None
                row.allocated_test_case_id = row.allocated_test_case_id or "a" + uuid.uuid4().hex[1:]
                row.import_status = "importing"
                row.save()
        batch.save()
        response = batch_data(batch)
        batch.commit_operations[operation_key] = {"fingerprint": fingerprint, "response": response}
        batch.save()
        return batch, response, True


def owned_paths(row):
    ident = row.allocated_test_case_id
    if not ident:
        return []
    import re
    if not re.fullmatch(r"[1-9a-f][0-9a-f]{31}", ident):
        raise RuntimeError("Invalid persisted allocation")
    root = Path(settings.TEST_CASE_DIR)
    return [root / (".import-" + ident), root / ident]


def clean_allocation(row):
    if not row.allocated_test_case_id or Problem.objects.filter(test_case_id=row.allocated_test_case_id).exists():
        return
    for path in owned_paths(row):
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)


def stage_test_cases(archive, entry, value, row):
    stage, final = owned_paths(row)
    stage.parent.mkdir(parents=True, exist_ok=True)
    if final.exists() or final.is_symlink():
        fail("FILE_CONFLICT", "预分配测试目录已存在")
    if stage.exists() or stage.is_symlink():
        clean_allocation(row)
    stage.mkdir(mode=0o710)
    info = {"spj": False, "test_cases": {}, "allow_public_test_case_download": False}
    for index, case in enumerate(value["test_case_score"], 1):
        result = {"input_name": case["input_name"], "output_name": case["output_name"]}
        for kind in ("input", "output"):
            filename = case[kind + "_name"]
            data = archive.read(entry["directory"] + "/testcase/" + filename, 64 * 1024 * 1024)
            path = stage / filename
            with open(path, "xb") as target:
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            path.chmod(0o640)
            result[kind + "_size"] = len(data)
            if kind == "output":
                result["stripped_output_md5"] = hashlib.md5(data.rstrip()).hexdigest()
        info["test_cases"][str(index)] = result
    with open(stage / "info", "x", encoding="utf-8") as target:
        json.dump(info, target, ensure_ascii=False)
        target.flush()
        os.fsync(target.fileno())
    (stage / "info").chmod(0o640)
    return stage, final


def import_one(row, value, staged, user):
    transaction_lock("problem_import_source", row.source_platform + ":" + row.source_id)
    binding = ExternalProblemBinding.objects.select_for_update().filter(
        source_platform=row.source_platform, source_id=row.source_id).first()
    if binding:
        if binding.latest_content_hash != row.content_hash:
            fail("SOURCE_UPDATED", "来源内容已变化，禁止自动覆盖")
        row.import_status, row.imported_problem = "duplicate", binding.problem
        binding.latest_collected_problem = row
        binding.save()
        row.save()
        return
    if value is None:
        fail("SOURCE_BINDING_CHANGED", "重复交付的来源绑定已变化，需要重新审核")
    if Problem.objects.filter(_id=value["display_id"], contest__isnull=True).exists():
        fail("DISPLAY_ID_CONFLICT", "公开题号已被其他来源占用")
    tags, unresolved = resolve_tags(row.standardized_data["tags_unified"])
    if unresolved and not any(i["code"] == "IMPORT_TAG_UNRESOLVED" for i in row.validation_errors):
        fail("TAG_CHANGED", "标签状态已变化，需要重新审核")
    problem = Problem.objects.create(
        _id=value["display_id"], title=value["title"], description=value["description"]["value"],
        input_description=value["input_description"]["value"], output_description=value["output_description"]["value"],
        hint=value["hint"]["value"], samples=value["samples"], test_case_score=value["test_case_score"],
        test_case_id=row.allocated_test_case_id, time_limit=value["time_limit"], memory_limit=value["memory_limit"],
        languages=SysOptions.language_names, template={}, rule_type=value["rule_type"],
        source=value["source"], created_by=user, visible=False, difficulty="Mid",
        total_score=sum(item["score"] for item in value["test_case_score"]) if value["rule_type"] == "OI" else 0,
    )
    problem.tags.set(tags)
    ExternalProblemBinding.objects.create(
        source_platform=row.source_platform, source_id=row.source_id, problem=problem,
        first_collected_problem=row, latest_collected_problem=row,
        first_content_hash=row.content_hash, latest_content_hash=row.content_hash)
    os.replace(*staged)
    row.imported_problem, row.import_status = problem, "imported"
    row.save()


def save_tag_candidates(batch):
    for mapping in batch.tag_mappings:
        # Do not replace active mappings or choose a knowledge point based on CSV.
        ExternalTagMapping.objects.get_or_create(
            source_platform=mapping["source_platform"], normalized_source_tag=mapping["normalized_source_tag"],
            defaults={"source_tag": mapping["source_tag"], "unified_tag": mapping["unified_tag"],
                      "confidence": mapping["confidence"], "status": "pending"},
        )


def mark_failed(row, error):
    row.refresh_from_db()
    row.import_status = "failed"
    value = error_issue(error, "COMMIT_FAILED")
    row.validation_errors.append(value)
    row.import_error_code = value["code"]
    row.import_error_message = value["message"]
    row.save()


def commit_batch(batch_id):
    from account.models import User
    from knowledge.services import knowledge_write

    # Fixed lock ordering with knowledge writers; a batch lock also excludes recovery.
    with worker_lock(batch_id) as acquired:
        if not acquired:
            return ProblemImportBatch.objects.get(pk=batch_id)
        batch = ProblemImportBatch.objects.get(pk=batch_id)
        if batch.status != "importing":
            return batch
        rows = list(batch.problems.filter(pk__in=batch.commit_request["selected_ids"]).defer("standardized_data", "raw_data"))
        user = User.objects.get(pk=batch.commit_request["user_id"])
        partial = batch.commit_request["allow_partial"]
        operation_error = None
        try:
            verify_archive_hash(batch)
            with Archive(batch.archive_path, batch.command_limits) as archive:
                archive.verify_files()
                metadata = {entry["problem_key"]: entry for _, entry in archive.metadata()}
                prepared = []
                for row in rows:
                    if row.import_status == "duplicate":
                        prepared.append((row, None, None))
                        continue
                    if row.import_status != "importing":
                        continue
                    try:
                        entry = metadata[row.standardized_data["problem_key"]]
                        value = archive.problem(row.standardized_data, entry)
                        staged = stage_test_cases(archive, entry, value, row)
                        prepared.append((row, entry, staged))
                        row.__dict__.pop("standardized_data", None)
                    except Exception as error:
                        if not partial:
                            raise
                        clean_allocation(row)
                        mark_failed(row, error)
                if partial:
                    mappings_saved = False
                    for row, entry, staged in prepared:
                        try:
                            with knowledge_write():
                                value = archive.problem(row.standardized_data, entry) if entry else None
                                import_one(row, value, staged, user)
                                if not mappings_saved:
                                    save_tag_candidates(batch)
                            mappings_saved = True
                        except Exception as error:
                            clean_allocation(row)
                            mark_failed(row, error)
                        finally:
                            row.__dict__.pop("standardized_data", None)
                else:
                    with knowledge_write():
                        for row, entry, staged in prepared:
                            value = archive.problem(row.standardized_data, entry) if entry else None
                            import_one(row, value, staged, user)
                            row.__dict__.pop("standardized_data", None)
                        save_tag_candidates(batch)
        except Exception as error:
            operation_error = error_issue(error, "COMMIT_FAILED")
            for row in rows:
                row.refresh_from_db()
                if row.import_status == "importing":
                    clean_allocation(row)
                    mark_failed(row, error)
            if not batch.problems.filter(import_status="failed").exists():
                batch.issues.append(operation_error)
        for row in rows:
            row.refresh_from_db()
            clean_allocation(row)
        recalculate(batch)
        failures = batch.problems.filter(import_status="failed").exists() or operation_error is not None
        successes = batch.problems.filter(import_status__in=("imported", "duplicate")).exists()
        batch.status = "partial" if failures and successes else "failed" if failures else "imported"
        batch.committed_time = timezone.now()
        batch.save()
        return batch


def recover_batches(age_seconds=3600):
    cutoff = timezone.now() - timedelta(seconds=age_seconds)
    recovered = 0
    for ident in ProblemImportBatch.objects.filter(
            status__in=("uploaded", "validating", "importing"), updated_time__lt=cutoff).values_list("pk", flat=True):
        with worker_lock(ident) as acquired:
            if not acquired:
                continue
            with transaction.atomic():
                transaction_lock("problem_import_batch", str(ident))
                batch = ProblemImportBatch.objects.select_for_update().get(pk=ident)
                if batch.status not in ("uploaded", "validating", "importing") or batch.updated_time >= cutoff:
                    continue
                if batch.status in ("uploaded", "validating"):
                    batch.problems.all().delete()
                    batch.status = "uploaded"
                    batch.save()
                else:
                    for row in batch.problems.filter(import_status="importing").defer("raw_data", "standardized_data"):
                        binding = ExternalProblemBinding.objects.filter(source_platform=row.source_platform,
                                                                        source_id=row.source_id).first()
                        if (binding and binding.latest_content_hash == row.content_hash
                                and binding.problem.test_case_id == row.allocated_test_case_id):
                            row.imported_problem, row.import_status = binding.problem, "imported"
                            row.save()
                        else:
                            clean_allocation(row)
                            mark_failed(row, ContractError("IMPORT_INTERRUPTED", "任务中断；未创建重复题目"))
                    recalculate(batch)
                    successes = batch.problems.filter(import_status__in=("imported", "duplicate")).exists()
                    failures = batch.problems.filter(import_status="failed").exists()
                    batch.status = "partial" if successes and failures else "imported" if successes else "failed"
                    batch.committed_time = timezone.now()
                    batch.save()
                recovered += 1
        if batch.status == "uploaded":
            validate_batch(batch.pk)
    return recovered


def report(batch):
    rows = batch.problems.defer("raw_data").iterator()
    return {"schema_version": "1.0.0", "batch_id": batch.batch_key, "status": batch.status,
            "generated_at": timezone.now().isoformat(), "summary": summary(batch),
            "problems": [{"id": row.pk, "line_number": row.line_number,
                          "problem_key": row.standardized_data["problem_key"], "source_platform": row.source_platform,
                          "source_id": row.source_id, "status": row.import_status,
                          "issues": row.validation_errors + (batch.issues if index == 0 else [])}
                         for index, row in enumerate(rows)]}

#!/usr/bin/env python3
"""Deterministically convert standardized JSONL input into a QDUOJ-compatible ZIP."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCHEMA_VERSION = "1.0.0"
FORMAT = "xmuoj-qduoj-batch"
PRODUCER_NAME = "xmuoj-jsonl-to-qduoj"
PRODUCER_VERSION = "1.0.0"
PLATFORM_ALIASES = {"luogu": "LUOGU", "codeforces": "CF", "leetcode": "LC"}
TAG_MAPPING_HEADER = ["source_platform", "source_tag", "unified_tag", "knowledge_code", "confidence"]
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class ContractError(ValueError):
    """The source fixture violates the frozen conversion contract."""


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _json_bytes(value: Any, *, pretty: bool = True) -> bytes:
    if pretty:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    parser.close()
    normalized = unicodedata.normalize("NFC", " ".join(parser.parts))
    return " ".join(normalized.split())


def content_hash(record: Dict[str, Any]) -> str:
    values = [
        record.get("title_cn") or record["title"],
        _visible_text(record["description_html"]),
        _visible_text(record["input_description_html"]),
        _visible_text(record["output_description_html"]),
        json.dumps(record["samples"], ensure_ascii=False, separators=(",", ":")),
    ]
    payload = "\n".join(unicodedata.normalize("NFC", value) for value in values)
    return _sha256(payload.encode("utf-8"))


def _safe_source_path(root: Path, relative: str) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or not posix.parts or any(part in ("", ".", "..") for part in posix.parts):
        raise ContractError(f"unsafe relative path: {relative!r}")
    target = (root / Path(*posix.parts)).resolve()
    resolved_root = root.resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ContractError(f"path escapes source root: {relative!r}") from exc
    if target.is_symlink():
        raise ContractError(f"symbolic links are forbidden: {relative!r}")
    return target


def _require_file(root: Path, relative: str) -> Path:
    path = _safe_source_path(root, relative)
    if not path.is_file():
        raise ContractError(f"required file does not exist: {relative}")
    return path


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid UTF-8 JSON: {path}") from exc


def _load_records(source_root: Path) -> List[Dict[str, Any]]:
    jsonl_path = _require_file(source_root, "problems.jsonl")
    records: List[Dict[str, Any]] = []
    for line_number, line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"problems.jsonl:{line_number}: invalid JSON") from exc
        if not isinstance(record, dict):
            raise ContractError(f"problems.jsonl:{line_number}: object required")
        record["_metadata_line"] = line_number
        records.append(record)
    return records


def _problem_key(record: Dict[str, Any]) -> str:
    explicit = record.get("problem_key")
    if explicit:
        key = explicit
    else:
        source_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(record.get("source_id", ""))).strip("-._")
        key = f"{record.get('source_platform', '')}_{source_id}"
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,150}", key):
        raise ContractError(f"invalid problem_key: {key!r}")
    return key


def display_id(source_platform: str, source_id: str) -> str:
    alias = PLATFORM_ALIASES.get(source_platform)
    if alias is None:
        alias = re.sub(r"[^A-Za-z0-9]+", "-", source_platform.upper()).strip("-")
    if not alias:
        raise ContractError(f"source platform cannot form a display id: {source_platform!r}")
    cleaned_id = re.sub(r"[^A-Za-z0-9_-]+", "-", source_id).strip("-_")
    source_key = f"{source_platform}:{source_id}"
    if not cleaned_id:
        cleaned_id = "ID-" + _sha256(source_key.encode("utf-8"))[:12]
    base = f"{alias}-{cleaned_id}"
    if len(base) <= 24:
        return base
    return f"{base[:15]}-{_sha256(source_key.encode('utf-8'))[:8]}"


def _verify_declared_hash(path: Path, expected: str, label: str) -> bytes:
    data = path.read_bytes()
    actual = _sha256(data)
    if actual != expected:
        raise ContractError(f"{label}: SHA-256 mismatch: expected {expected}, got {actual}")
    return data


def _normalize_test_data(data: bytes) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("test data must be UTF-8 in phase one") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _validate_tag_mapping(source_root: Path) -> bytes:
    path = _require_file(source_root, "tag_mapping.csv")
    data = path.read_bytes()
    try:
        rows = list(csv.reader(data.decode("utf-8-sig").splitlines()))
    except UnicodeDecodeError as exc:
        raise ContractError("tag_mapping.csv must be UTF-8") from exc
    if not rows or rows[0] != TAG_MAPPING_HEADER:
        raise ContractError("tag_mapping.csv header does not match the frozen contract")
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _build_problem_json(record: Dict[str, Any], testcase_scores: List[Dict[str, Any]]) -> Dict[str, Any]:
    title = (record.get("title_cn") or record.get("title") or "").strip()
    if not title or len(title) > 128:
        raise ContractError(f"QDUOJ title length must be 1..128: {title!r}")
    source = record.get("source_url")
    if source is not None and len(source) > 200:
        raise ContractError("QDUOJ source URL exceeds 200 characters")
    return {
        "display_id": display_id(str(record["source_platform"]), str(record["source_id"])),
        "title": title,
        "description": {"format": "html", "value": record["description_html"]},
        "input_description": {"format": "html", "value": record["input_description_html"]},
        "output_description": {"format": "html", "value": record["output_description_html"]},
        "hint": {"format": "html", "value": record.get("hint_html") or ""},
        "test_case_score": testcase_scores,
        "time_limit": record["time_limit_ms"],
        "memory_limit": record["memory_limit_mb"],
        "samples": record["samples"],
        "template": {},
        "spj": None,
        "rule_type": record.get("rule_type", "ACM"),
        "source": source,
        "allow_public_test_case_download": False,
        "answers": [],
        "tags": record["tags_unified"],
    }


def _testcase_files(
    source_root: Path, record: Dict[str, Any], directory: str
) -> Tuple[Dict[str, bytes], List[Dict[str, Any]]]:
    judge_data = record.get("judge_data") or {}
    manifest_path = judge_data.get("testcase_manifest_path")
    if not manifest_path:
        raise ContractError(f"{_problem_key(record)}: ready record needs testcase_manifest_path")
    manifest = _load_json(_require_file(source_root, manifest_path))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"{_problem_key(record)}: unsupported testcase schema version")
    if manifest.get("spj") is not False:
        raise ContractError(f"{_problem_key(record)}: phase-one builder refuses SPJ")
    rule_type = record.get("rule_type", "ACM")
    if manifest.get("rule_type") != rule_type:
        raise ContractError(f"{_problem_key(record)}: rule_type differs from testcase manifest")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ContractError(f"{_problem_key(record)}: at least one testcase is required")
    package_files: Dict[str, bytes] = {}
    scores: List[Dict[str, Any]] = []
    seen_ids = set()
    oi_total = 0
    for index, case in enumerate(cases, start=1):
        case_id = case.get("id")
        if case_id in seen_ids:
            raise ContractError(f"{_problem_key(record)}: duplicate testcase id {case_id!r}")
        seen_ids.add(case_id)
        input_data = _verify_declared_hash(
            _require_file(source_root, case["input_path"]), case["input_sha256"], f"case {case_id} input"
        )
        output_data = _verify_declared_hash(
            _require_file(source_root, case["output_path"]), case["output_sha256"], f"case {case_id} output"
        )
        input_name, output_name = f"{index}.in", f"{index}.out"
        package_files[f"{directory}/testcase/{input_name}"] = _normalize_test_data(input_data)
        package_files[f"{directory}/testcase/{output_name}"] = _normalize_test_data(output_data)
        if rule_type == "ACM":
            if case.get("score") is not None or manifest.get("total_score") is not None:
                raise ContractError(f"{_problem_key(record)}: ACM score and total_score must be null")
            score = 100
        else:
            score = case.get("score")
            if not isinstance(score, int) or isinstance(score, bool) or score < 1:
                raise ContractError(f"{_problem_key(record)}: OI score must be a positive integer")
            oi_total += score
        scores.append({"score": score, "input_name": input_name, "output_name": output_name})
    if rule_type == "OI" and manifest.get("total_score") != oi_total:
        raise ContractError(f"{_problem_key(record)}: OI testcase scores do not equal total_score")
    return package_files, scores


def _media_type(path: str) -> str:
    if path.endswith(".json"):
        return "application/json"
    if path.endswith(".jsonl"):
        return "application/x-ndjson"
    if path.endswith(".csv"):
        return "text/csv"
    return "text/plain"


def build_package(
    source_root: Path,
    *,
    batch_id: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> Tuple[Dict[str, bytes], Dict[str, Any]]:
    source_root = source_root.resolve()
    source_manifest_path = source_root / "build-config.json"
    source_manifest = _load_json(source_manifest_path) if source_manifest_path.is_file() else {}
    actual_batch_id = batch_id or source_manifest.get("batch_id")
    if not isinstance(actual_batch_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", actual_batch_id):
        raise ContractError("batch_id is required and must match [A-Za-z0-9._-]{1,64}")
    actual_generated_at = generated_at or source_manifest.get("generated_at")
    if not actual_generated_at:
        actual_generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        datetime.fromisoformat(actual_generated_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ContractError("generated_at must be an ISO 8601 date-time") from exc

    records = _load_records(source_root)
    keys = [_problem_key(record) for record in records]
    if len(set(keys)) != len(keys):
        raise ContractError("problem_key must be unique inside a batch")
    source_keys = [(record.get("source_platform"), record.get("source_id")) for record in records]
    if len(set(source_keys)) != len(source_keys):
        raise ContractError("source_platform/source_id must be unique inside a batch")

    package_files: Dict[str, bytes] = {"tag_mapping.csv": _validate_tag_mapping(source_root)}
    packaged_records: List[Dict[str, Any]] = []
    problem_entries: List[Dict[str, Any]] = []
    next_directory = 1
    for record, key in zip(records, keys):
        metadata_line = record.pop("_metadata_line")
        declared_content_hash = record.get("content_hash")
        if declared_content_hash and declared_content_hash != content_hash(record):
            raise ContractError(f"{key}: content_hash does not match normalized content")
        status = (record.get("judge_data") or {}).get("status", "statement_only")
        directory: Optional[str] = None
        if status == "ready":
            directory = str(next_directory)
            next_directory += 1
            testcase_files, scores = _testcase_files(source_root, record, directory)
            package_files.update(testcase_files)
            package_files[f"{directory}/problem.json"] = _json_bytes(_build_problem_json(record, scores))
        elif status not in ("statement_only", "needs_review"):
            raise ContractError(f"{key}: invalid judge_data.status {status!r}")

        packaged = dict(record)
        packaged.pop("judge_data", None)
        raw_data_path = record.get("raw_data_path")
        if raw_data_path:
            raw_data = _require_file(source_root, raw_data_path).read_bytes()
            packaged_raw_path = f"metadata/raw/{key}.json"
            package_files[packaged_raw_path] = raw_data
            packaged["raw_data_path"] = packaged_raw_path
        packaged_records.append(packaged)
        problem_entries.append(
            {
                "problem_key": key,
                "metadata_line": metadata_line,
                "directory": directory,
                "delivery_status": status,
                "metadata_path": "metadata/problems.jsonl",
            }
        )

    package_files["metadata/problems.jsonl"] = b"".join(_json_bytes(record, pretty=False) for record in packaged_records)
    file_entries = [
        {
            "path": path,
            "media_type": _media_type(path),
            "size_bytes": len(data),
            "sha256": _sha256(data),
        }
        for path, data in sorted(package_files.items())
    ]
    producer = source_manifest.get("producer") if isinstance(source_manifest.get("producer"), dict) else {}
    manifest: Dict[str, Any] = {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "batch_id": actual_batch_id,
        "generated_at": actual_generated_at,
        "producer": {
            "name": producer.get("name", PRODUCER_NAME),
            "version": producer.get("version", PRODUCER_VERSION),
        },
        "source_platforms": sorted({str(record["source_platform"]) for record in records}),
        "problem_count": len(records),
        "importable_count": sum(entry["directory"] is not None for entry in problem_entries),
        "problems": problem_entries,
        "files": file_entries,
    }
    if producer.get("contact"):
        manifest["producer"]["contact"] = producer["contact"]
    package_files["manifest.json"] = _json_bytes(manifest)
    return package_files, manifest


def write_expanded(package_files: Dict[str, bytes], output_dir: Path, *, replace: bool = False) -> None:
    output_dir = output_dir.resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists():
        if not output_dir.is_dir() or output_dir.is_symlink():
            raise ContractError(f"expanded output is not a regular directory: {output_dir}")
        if not replace:
            raise ContractError("expanded output already exists; pass --replace-expanded to replace it")
        forbidden = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve()}
        if output_dir in forbidden or len(output_dir.parts) < 3:
            raise ContractError(f"refusing to replace broad directory: {output_dir}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        for relative, data in sorted(package_files.items()):
            target = temporary / Path(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temporary.replace(output_dir)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def write_zip(package_files: Dict[str, bytes], output_zip: Path) -> None:
    output_zip = output_zip.resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_zip.with_name(output_zip.name + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, data in sorted(package_files.items()):
            info = zipfile.ZipInfo(relative, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temporary.replace(output_zip)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path, help="directory containing problems.jsonl and source attachments")
    parser.add_argument("output_zip", type=Path, help="QDUOJ-compatible ZIP to create")
    parser.add_argument("--expanded-dir", type=Path, help="also write an expanded golden package")
    parser.add_argument(
        "--replace-expanded", action="store_true", help="replace an existing explicit expanded output directory"
    )
    parser.add_argument("--batch-id", help="override source manifest batch_id")
    parser.add_argument("--generated-at", help="fixed ISO 8601 timestamp for reproducible builds")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        package_files, manifest = build_package(
            args.source_dir, batch_id=args.batch_id, generated_at=args.generated_at
        )
        write_zip(package_files, args.output_zip)
        if args.expanded_dir:
            write_expanded(package_files, args.expanded_dir, replace=args.replace_expanded)
    except ContractError as exc:
        parser.exit(1, f"contract error: {exc}\n")
    print(
        f"built {args.output_zip}: {manifest['problem_count']} records, "
        f"{manifest['importable_count']} QDUOJ problems"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

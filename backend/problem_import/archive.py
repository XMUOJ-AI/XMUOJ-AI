"""Bounded, non-extracting reader for the formal QDUOJ delivery format."""
import codecs
import csv
import hashlib
import io
import json
import re
import stat
import unicodedata
import zipfile
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from utils.contract_api import ContractError

MIB = 1024 * 1024
WEB_LIMIT = 256 * MIB
COMMAND_LIMIT = 2048 * MIB
LINE_LIMIT = 2 * MIB
FILE_LIMIT = 64 * MIB
MANIFEST_LIMIT = 16 * MIB
TAG_HEADER = ["source_platform", "source_tag", "unified_tag", "knowledge_code", "confidence"]


def fail(code, message, field=None):
    raise ContractError("IMPORT_" + code, message, details={"field": field})


def issue(code, message, field=None, level="error"):
    return {"code": "IMPORT_" + code, "message": message, "field": field, "level": level}


def strict_json(data):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                fail("JSON_INVALID", "JSON 对象字段重复")
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda value: fail("JSON_INVALID", "JSON 包含非有限数字"))
    except (ValueError, UnicodeError, RecursionError):
        fail("JSON_INVALID", "文件不是有效的 UTF-8 JSON")


@lru_cache(maxsize=8)
def validator(name):
    schema = strict_json((Path(__file__).parent / "schemas" / (name + ".schema.json")).read_bytes())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def schema_errors(value, name):
    errors = []
    try:
        for error in validator(name).iter_errors(value):
            errors.append(issue("SCHEMA_INVALID", "字段不符合交付 Schema",
                                ".".join(str(part) for part in error.absolute_path) or "$"))
            if len(errors) >= 50:
                break
    except RecursionError:
        errors.append(issue("SCHEMA_INVALID", "JSON 嵌套过深", "$"))
    return errors


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def content_hash(record):
    values = [record.get("title_cn") or record["title"]]
    for key in ("description_html", "input_description_html", "output_description_html"):
        parser = VisibleText()
        parser.feed(record[key])
        parser.close()
        values.append(" ".join(unicodedata.normalize("NFC", " ".join(parser.parts)).split()))
    values.append(json.dumps(record["samples"], ensure_ascii=False, separators=(",", ":")))
    return hashlib.sha256("\n".join(unicodedata.normalize("NFC", value) for value in values).encode()).hexdigest()


def display_id(platform, source_id):
    alias = {"luogu": "LUOGU", "codeforces": "CF", "leetcode": "LC"}.get(platform)
    alias = alias or re.sub(r"[^A-Za-z0-9]+", "-", platform.upper()).strip("-")
    digest = hashlib.sha256((platform + ":" + source_id).encode()).hexdigest()
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", source_id).strip("-_") or "ID-" + digest[:12]
    base = alias + "-" + clean
    return base if len(base) <= 24 else base[:15] + "-" + digest[:8]


def expected_problem(record, scores):
    result = {
        "display_id": display_id(record["source_platform"], record["source_id"]),
        "title": (record.get("title_cn") or record["title"]).strip(),
        "hint": {"format": "html", "value": record.get("hint_html") or ""},
        "test_case_score": scores, "time_limit": record["time_limit_ms"],
        "memory_limit": record["memory_limit_mb"], "samples": record["samples"],
        "template": {}, "spj": None, "rule_type": record.get("rule_type", "ACM"),
        "source": record["source_url"], "allow_public_test_case_download": False,
        "answers": [], "tags": record["tags_unified"],
    }
    for key in ("description", "input_description", "output_description"):
        result[key] = {"format": "html", "value": record[key + "_html"]}
    return result


class Archive:
    def __init__(self, path, command=False):
        self.path = Path(path)
        self.limit = COMMAND_LIMIT if command else WEB_LIMIT
        self.count_limit = 5000 if command else 500
        if self.path.is_symlink() or not self.path.is_file():
            fail("FILE_INVALID", "数据包必须是普通文件")
        if self.path.stat().st_size > self.limit:
            fail("SIZE_LIMIT", "ZIP 超过入口大小限制")
        try:
            self.zip = zipfile.ZipFile(self.path)
        except (zipfile.BadZipFile, OSError):
            fail("ZIP_INVALID", "文件不是有效的 ZIP")
        try:
            self.files = {}
            total = 0
            entries = self.zip.infolist()
            if len(entries) > 100000:
                fail("SIZE_LIMIT", "ZIP 文件条目过多")
            for entry in entries:
                name = entry.filename
                if (not re.fullmatch(r"[A-Za-z0-9._/-]{1,500}", name)
                        or any(part in ("", ".", "..") for part in name.rstrip("/").split("/"))):
                    fail("UNSAFE_PATH", "ZIP 含不安全路径")
                mode = entry.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if entry.flag_bits & 1 or kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    fail("UNSAFE_ARCHIVE", "ZIP 不允许加密或特殊文件")
                if not entry.is_dir() and mode & 0o111:
                    fail("UNSAFE_ARCHIVE", "ZIP 不允许可执行文件")
                if name in self.files:
                    fail("DUPLICATE_PATH", "ZIP 含重复路径")
                if entry.is_dir():
                    continue
                if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    fail("UNSAFE_ARCHIVE", "不支持该 ZIP 压缩算法")
                if entry.file_size > COMMAND_LIMIT or entry.file_size > max(entry.compress_size, 1) * 1000:
                    fail("ZIP_BOMB", "文件大小或压缩比异常")
                total += entry.file_size
                if total > COMMAND_LIMIT:
                    fail("ZIP_BOMB", "ZIP 解压总量超过 2 GiB 安全限制")
                self.files[name] = entry
            self.manifest = self.read_json("manifest.json", MANIFEST_LIMIT)
            errors = schema_errors(self.manifest, "problem-batch-manifest-v1")
            if errors:
                fail("MANIFEST_INVALID", "manifest 不符合 Schema", errors[0]["field"])
            if self.manifest["problem_count"] > self.count_limit:
                fail("SIZE_LIMIT", "批次题目数超过入口限制")
        except Exception:
            self.zip.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.zip.close()

    def read(self, name, limit=LINE_LIMIT):
        entry = self.files.get(name)
        if not entry:
            fail("MISSING_FILE", "缺少交付文件", name)
        if entry.file_size > limit:
            fail("SIZE_LIMIT", "文件超过大小限制", name)
        try:
            with self.zip.open(entry) as source:
                data = source.read(limit + 1)
            if len(data) > limit:
                fail("SIZE_LIMIT", "文件超过大小限制", name)
            return data
        except (zipfile.BadZipFile, RuntimeError, OSError):
            fail("ZIP_INVALID", "ZIP 条目读取或 CRC 校验失败", name)

    def read_json(self, name, limit=LINE_LIMIT):
        return strict_json(self.read(name, limit))

    def verify_files(self):
        declared = {}
        for item in self.manifest["files"]:
            path = item["path"]
            if path in declared or path == "manifest.json":
                fail("MANIFEST_INVALID", "manifest 文件声明重复或自引用", path)
            declared[path] = item
        if set(declared) != set(self.files) - {"manifest.json"}:
            fail("FILE_SET_MISMATCH", "ZIP 实际文件与 manifest 声明不一致")
        if not {"metadata/problems.jsonl", "tag_mapping.csv"}.issubset(declared):
            fail("MISSING_FILE", "缺少 metadata 或标签映射文件")
        for path, item in declared.items():
            if self.files[path].file_size != item["size_bytes"]:
                fail("FILE_SIZE_MISMATCH", "文件大小与声明不一致", path)
            if re.fullmatch(r"(?:metadata/raw/[A-Za-z0-9._/-]+|[1-9][0-9]*/problem)\.json", path):
                expected_type = "application/json"
            elif path == "metadata/problems.jsonl":
                expected_type = "application/x-ndjson"
            elif path == "tag_mapping.csv":
                expected_type = "text/csv"
            elif path.startswith("assets/"):
                self.verify_image(path, item)
                continue
            elif re.fullmatch(r"[1-9][0-9]*/testcase/[1-9][0-9]*\.(in|out)", path):
                expected_type = "text/plain"
                if item["size_bytes"] > FILE_LIMIT:
                    fail("SIZE_LIMIT", "单个测试文件超过 64 MiB", path)
            else:
                fail("UNSUPPORTED_FILE", "不支持的交付文件类型", path)
            if item["media_type"] != expected_type:
                fail("MEDIA_TYPE_MISMATCH", "文件媒体类型与用途不一致", path)
            digest = hashlib.sha256()
            decoder = codecs.getincrementaldecoder("utf-8")()
            size = 0
            try:
                with self.zip.open(path) as source:
                    while True:
                        chunk = source.read(MIB)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > item["size_bytes"]:
                            fail("SIZE_LIMIT", "实际文件超过声明大小", path)
                        if b"\r" in chunk or b"\x00" in chunk:
                            fail("TEXT_INVALID", "文本必须使用 LF 且不可包含 NUL", path)
                        decoder.decode(chunk)
                        digest.update(chunk)
                    decoder.decode(b"", final=True)
            except UnicodeError:
                fail("TEXT_INVALID", "文本必须为 UTF-8", path)
            except (zipfile.BadZipFile, RuntimeError, OSError):
                fail("ZIP_INVALID", "ZIP 条目读取或 CRC 校验失败", path)
            if digest.hexdigest() != item["sha256"]:
                fail("FILE_HASH_MISMATCH", "文件 SHA-256 与声明不一致", path)

    def verify_image(self, path, item):
        from PIL import Image, UnidentifiedImageError
        import xml.etree.ElementTree as ET

        data = self.read(path, 20 * MIB)
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            fail("FILE_HASH_MISMATCH", "媒体资源 SHA-256 不一致", path)
        if item["media_type"] == "image/svg+xml":
            if b"<!" in data or b"<?" in data.replace(b'<?xml version="1.0"?>', b""):
                fail("MEDIA_TYPE_MISMATCH", "SVG 不允许声明或实体", path)
            try:
                root = ET.fromstring(data)
            except (ET.ParseError, ValueError):
                fail("MEDIA_TYPE_MISMATCH", "SVG XML 不合法", path)
            if root.tag.rsplit("}", 1)[-1] != "svg":
                fail("MEDIA_TYPE_MISMATCH", "SVG 缺少根元素", path)
            allowed = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
                       "text", "tspan", "defs", "linearGradient", "radialGradient", "stop", "title", "desc"}
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] not in allowed:
                    fail("UNSAFE_MEDIA", "SVG 含不允许的元素", path)
                for key, value in node.attrib.items():
                    if key.lower().startswith("on") or "href" in key.lower() or "url(" in value.lower() or key == "style":
                        fail("UNSAFE_MEDIA", "SVG 含活动或外部资源属性", path)
            return
        formats = {"image/png": "PNG", "image/jpeg": "JPEG", "image/gif": "GIF", "image/webp": "WEBP"}
        try:
            with Image.open(io.BytesIO(data)) as image:
                if formats.get(item["media_type"]) != image.format or image.width * image.height > 40000000:
                    fail("MEDIA_TYPE_MISMATCH", "图片实际类型或尺寸不合法", path)
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            fail("MEDIA_TYPE_MISMATCH", "图片内容与声明不一致", path)

    def metadata(self):
        entries = self.manifest["problems"]
        if len(entries) != self.manifest["problem_count"]:
            fail("COUNT_MISMATCH", "manifest 题目数不一致")
        directories = [entry["directory"] for entry in entries if entry["directory"] is not None]
        if directories != [str(i) for i in range(1, len(directories) + 1)]:
            fail("MANIFEST_INVALID", "可导入目录必须从 1 连续编号")
        if len(directories) != self.manifest["importable_count"]:
            fail("COUNT_MISMATCH", "importable_count 不一致")
        actual_dirs = {name.split("/")[0] for name in self.files if name[0].isdigit()}
        if actual_dirs != set(directories):
            fail("FILE_SET_MISMATCH", "数字目录与 manifest 不一致")
        count, line_number = 0, 0
        keys, sources = set(), set()
        with self.zip.open("metadata/problems.jsonl") as source:
            while True:
                raw = source.readline(LINE_LIMIT + 1)
                if not raw:
                    break
                line_number += 1
                if len(raw) > LINE_LIMIT:
                    fail("SIZE_LIMIT", "JSONL 单行超过 2 MiB", "metadata/problems.jsonl")
                if not raw.strip():
                    continue
                count += 1
                if count > self.count_limit or count > len(entries):
                    fail("COUNT_MISMATCH", "metadata 记录数超过 manifest 或入口限制")
                record, entry = strict_json(raw), entries[count - 1]
                if line_number != entry["metadata_line"] or entry["problem_key"] in keys:
                    fail("MANIFEST_INVALID", "manifest 题目行号或 problem_key 不一致")
                keys.add(entry["problem_key"])
                if isinstance(record, dict):
                    identity = (record.get("source_platform"), record.get("source_id"))
                    if all(isinstance(value, str) for value in identity):
                        if identity in sources:
                            fail("DUPLICATE_SOURCE", "批次内来源身份重复")
                        sources.add(identity)
                    if record.get("problem_key", entry["problem_key"]) != entry["problem_key"]:
                        fail("MANIFEST_INVALID", "manifest 与 metadata 的 problem_key 不一致")
                yield ((line_number, record), entry)
        if count != self.manifest["problem_count"]:
            fail("COUNT_MISMATCH", "metadata 记录数与 manifest 不一致")

    def mappings(self):
        from decimal import Decimal, InvalidOperation
        from problem.tag import normalize_tag_name

        rows = csv.DictReader(io.StringIO(self.read("tag_mapping.csv", MANIFEST_LIMIT).decode("utf-8")))
        if rows.fieldnames != TAG_HEADER:
            fail("TAG_MAPPING_INVALID", "标签映射 CSV 表头错误")
        result, seen = [], set()
        for row in rows:
            if set(row) != set(TAG_HEADER) or any(value is None for value in row.values()):
                fail("TAG_MAPPING_INVALID", "标签映射 CSV 列数错误")
            normalized = normalize_tag_name(row["source_tag"])
            key = (row["source_platform"], normalized)
            if (not re.fullmatch(r"[a-z][a-z0-9_-]{0,49}", row["source_platform"])
                    or not normalized or any(len(row[field]) > 128 for field in TAG_HEADER[1:-1])):
                fail("TAG_MAPPING_INVALID", "标签映射字段不合法")
            if key in seen:
                fail("TAG_MAPPING_CONFLICT", "同平台规范化来源标签重复")
            try:
                confidence = Decimal(row["confidence"])
                if not confidence.is_finite() or not 0 <= confidence <= 1 or confidence.as_tuple().exponent < -3:
                    raise ValueError()
            except (InvalidOperation, ValueError):
                fail("TAG_MAPPING_INVALID", "标签映射置信度不合法")
            seen.add(key)
            result.append(dict(row, normalized_source_tag=normalized))
        return result

    def problem(self, record, entry):
        directory = entry["directory"]
        if directory is None:
            return None
        value = self.read_json(directory + "/problem.json")
        errors = schema_errors(value, "qduoj-problem-v1")
        if errors:
            fail("SCHEMA_INVALID", "problem.json 不符合 Schema", errors[0]["field"])
        scores = value["test_case_score"]
        if not scores:
            fail("TESTCASE_INVALID", "至少需要一组测试数据")
        expected_files, total = set(), 0
        for index, score in enumerate(scores, 1):
            if score["input_name"] != f"{index}.in" or score["output_name"] != f"{index}.out":
                fail("TESTCASE_INVALID", "测试文件必须按顺序连续编号")
            if value["rule_type"] == "ACM" and score["score"] != 100:
                fail("TESTCASE_INVALID", "ACM 测试点分数必须为 100")
            for name in (score["input_name"], score["output_name"]):
                path = directory + "/testcase/" + name
                if path not in self.files:
                    fail("MISSING_FILE", "测试输入或输出缺失", path)
                expected_files.add(path)
                total += self.files[path].file_size
        if total > 512 * MIB:
            fail("SIZE_LIMIT", "单题测试数据超过 512 MiB")
        if {name for name in self.files if name.startswith(directory + "/")} != expected_files | {directory + "/problem.json"}:
            fail("TESTCASE_INVALID", "题目目录含未使用文件")
        if value != expected_problem(record, scores):
            fail("METADATA_MISMATCH", "problem.json 与标准化记录的确定性转换不一致")
        return value

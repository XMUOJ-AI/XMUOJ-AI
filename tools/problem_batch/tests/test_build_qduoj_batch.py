import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "tools/problem_batch/build_qduoj_batch.py"
SPEC = importlib.util.spec_from_file_location("build_qduoj_batch", MODULE_PATH)
builder = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(builder)
SOURCE_FIXTURE = REPO_ROOT / "docs/examples/problem-batch-example"
GOLDEN_ZIP = REPO_ROOT / "docs/examples/problem-batch-example.zip"


def load_source_record():
    return json.loads((SOURCE_FIXTURE / "problems.jsonl").read_text(encoding="utf-8"))


class BuildQduojBatchTests(unittest.TestCase):
    def test_golden_zip_is_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            output_one = Path(directory) / "one.zip"
            output_two = Path(directory) / "two.zip"
            for output in (output_one, output_two):
                files, manifest = builder.build_package(
                    SOURCE_FIXTURE, generated_at="2026-08-09T10:00:00Z"
                )
                self.assertEqual(manifest["importable_count"], 1)
                builder.write_zip(files, output)
            self.assertEqual(output_one.read_bytes(), output_two.read_bytes())
            self.assertEqual(output_one.read_bytes(), GOLDEN_ZIP.read_bytes())

    def test_manifest_hashes_every_payload_file(self):
        with zipfile.ZipFile(GOLDEN_ZIP) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            declared = {item["path"]: item for item in manifest["files"]}
            actual = set(archive.namelist()) - {"manifest.json"}
            self.assertEqual(set(declared), actual)
            for path, item in declared.items():
                data = archive.read(path)
                self.assertEqual(item["size_bytes"], len(data))
                self.assertEqual(item["sha256"], hashlib.sha256(data).hexdigest())

    def test_qduoj_problem_matches_existing_import_serializer_shape(self):
        with zipfile.ZipFile(GOLDEN_ZIP) as archive:
            problem = json.loads(archive.read("1/problem.json"))
        self.assertEqual(problem["display_id"], "LUOGU-P1001")
        self.assertEqual(problem["description"]["format"], "html")
        self.assertEqual(problem["test_case_score"][0]["score"], 100)
        self.assertEqual(problem["test_case_score"][0]["input_name"], "1.in")
        self.assertIsNone(problem["spj"])
        self.assertFalse(problem["allow_public_test_case_download"])

    def test_statement_only_is_metadata_only(self):
        record = load_source_record()
        record["judge_data"] = {"status": "statement_only", "testcase_manifest_path": None}
        record.pop("raw_data_path", None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "problems.jsonl").write_text(
                json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            (root / "tag_mapping.csv").write_text(
                ",".join(builder.TAG_MAPPING_HEADER) + "\n", encoding="utf-8"
            )
            files, manifest = builder.build_package(
                root, batch_id="statement-only", generated_at="2026-08-09T10:00:00Z"
            )
        self.assertEqual(manifest["problem_count"], 1)
        self.assertEqual(manifest["importable_count"], 0)
        self.assertIsNone(manifest["problems"][0]["directory"])
        self.assertFalse(any(path.startswith("1/") for path in files))

    def test_unsafe_raw_path_is_rejected(self):
        record = load_source_record()
        record["raw_data_path"] = "../secret.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "problems.jsonl").write_text(
                json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            (root / "tag_mapping.csv").write_text(
                ",".join(builder.TAG_MAPPING_HEADER) + "\n", encoding="utf-8"
            )
            with self.assertRaises(builder.ContractError):
                builder.build_package(root, batch_id="unsafe", generated_at="2026-08-09T10:00:00Z")

    def test_duplicate_source_key_is_rejected(self):
        record = load_source_record()
        second = copy.deepcopy(record)
        second["problem_key"] = "luogu_P1001_copy"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "problems.jsonl").write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in (record, second)) + "\n",
                encoding="utf-8",
            )
            (root / "tag_mapping.csv").write_text(
                ",".join(builder.TAG_MAPPING_HEADER) + "\n", encoding="utf-8"
            )
            with self.assertRaises(builder.ContractError):
                builder.build_package(root, batch_id="duplicate", generated_at="2026-08-09T10:00:00Z")


if __name__ == "__main__":
    unittest.main()

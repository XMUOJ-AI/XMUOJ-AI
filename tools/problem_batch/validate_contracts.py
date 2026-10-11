#!/usr/bin/env python3
"""Validate frozen JSON Schemas, examples, OpenAPI documents and golden package."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import zipfile
from pathlib import Path

try:
    import yaml
    from jsonschema import Draft202012Validator, FormatChecker, ValidationError
    from openapi_spec_validator import validate_spec
except ImportError as exc:  # pragma: no cover - gives a useful local setup message
    raise SystemExit(
        "install tools/problem_batch/requirements-contract.txt before validation: " + str(exc)
    )


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "docs" / "schemas"
EXAMPLES = REPO_ROOT / "docs/examples"
OPENAPI = REPO_ROOT / "docs" / "openapi"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_schema(name: str):
    schema = load_json(SCHEMAS / name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def assert_rejected(validator, value, label: str):
    try:
        validator.validate(value)
    except ValidationError:
        return
    raise AssertionError(f"negative example was accepted: {label}")


def validate_json_contracts():
    for path in SCHEMAS.glob("*.json"):
        Draft202012Validator.check_schema(load_json(path))
    collection = load_schema("collection-config-v1.schema.json")
    problem = load_schema("problem-import-v1.schema.json")
    testcase = load_schema("problem-testcase-manifest-v1.schema.json")
    qduoj = load_schema("qduoj-problem-v1.schema.json")
    batch = load_schema("problem-batch-manifest-v1.schema.json")
    report = load_schema("problem-import-report-v1.schema.json")

    collection_example = load_json(EXAMPLES / "collection_config.json")
    collection.validate(collection_example)
    invalid_collection = copy.deepcopy(collection_example)
    invalid_collection["compliance"]["respect_robots_txt"] = False
    assert_rejected(collection, invalid_collection, "robots.txt cannot be disabled")

    source_record = json.loads(
        (EXAMPLES / "problem-batch-example/problems.jsonl").read_text(encoding="utf-8")
    )
    problem.validate(source_record)
    invalid_record = copy.deepcopy(source_record)
    invalid_record["raw_data_path"] = "../secret.json"
    assert_rejected(problem, invalid_record, "raw path traversal")

    testcase_example = load_json(
        EXAMPLES / "problem-batch-example/testcases/luogu_P1001/manifest.json"
    )
    testcase.validate(testcase_example)
    invalid_testcase = copy.deepcopy(testcase_example)
    invalid_testcase["cases"][0]["score"] = 100
    assert_rejected(testcase, invalid_testcase, "ACM testcase score must be null in source manifest")

    expanded = EXAMPLES / "qduoj-problem-batch-example"
    qduoj_example = load_json(expanded / "1/problem.json")
    qduoj.validate(qduoj_example)
    invalid_qduoj = copy.deepcopy(qduoj_example)
    invalid_qduoj["test_case_score"][0]["score"] = 0
    assert_rejected(qduoj, invalid_qduoj, "existing serializer rejects score zero")

    manifest = load_json(expanded / "manifest.json")
    batch.validate(manifest)
    invalid_manifest = copy.deepcopy(manifest)
    invalid_manifest["problems"][0]["directory"] = None
    assert_rejected(batch, invalid_manifest, "ready record requires numeric directory")

    for line in (expanded / "metadata/problems.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            problem.validate(json.loads(line))
    report.validate(load_json(EXAMPLES / "problem-import-report.json"))


def validate_openapi_contracts():
    for path in sorted(OPENAPI.glob("*.yaml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        validate_spec(spec)
        expected_version = "0.9.9" if path.name == "knowledge-api-v1.yaml" else "1.0.0"
        assert spec["info"]["version"] == expected_version
        assert "request_id" in spec["components"]["schemas"]["ErrorEnvelope"]["required"]

    import_spec = yaml.safe_load((OPENAPI / "problem-import-api-v1.yaml").read_text(encoding="utf-8"))
    commit = import_spec["paths"]["/batches/{batch_id}/commit"]["post"]
    parameter_refs = {item.get("$ref") for item in commit["parameters"]}
    assert "#/components/parameters/IdempotencyKey" in parameter_refs
    assert "#/components/parameters/CsrfToken" in parameter_refs
    limit = import_spec["components"]["parameters"]["Limit"]["schema"]
    assert limit == {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}
    problem_ids = import_spec["components"]["schemas"]["CommitRequest"]["properties"]["problem_ids"]
    assert "CollectedProblem.id" in problem_ids["description"]

    agent_spec = yaml.safe_load((OPENAPI / "agent-api-v1.yaml").read_text(encoding="utf-8"))
    create_run = agent_spec["components"]["schemas"]["CreateRunRequest"]
    assert len(create_run["oneOf"]) == 4
    result = agent_spec["components"]["schemas"]["Run"]["properties"]["result"]
    assert len(result["oneOf"]) == 5
    assert {"type": "object", "nullable": True, "enum": [None]} in result["oneOf"]


def validate_golden_hashes():
    zip_path = EXAMPLES / "problem-batch-example.zip"
    with zipfile.ZipFile(zip_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        names = set(archive.namelist())
        declared = {item["path"]: item for item in manifest["files"]}
        assert names - {"manifest.json"} == set(declared)
        for path, item in declared.items():
            data = archive.read(path)
            assert len(data) == item["size_bytes"]
            assert hashlib.sha256(data).hexdigest() == item["sha256"]
            assert data == (EXAMPLES / "qduoj-problem-batch-example" / path).read_bytes()


def main():
    validate_json_contracts()
    validate_openapi_contracts()
    validate_golden_hashes()
    print("contract validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

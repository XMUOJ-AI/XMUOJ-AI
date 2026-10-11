"""Run only in disposable xmuoj_h7 database after bootstrap."""
import hashlib
import json
import os
from pathlib import Path

from django.conf import settings
from account.models import User
from knowledge.models import KnowledgePoint, ProblemKnowledge
from problem.models import Problem

assert settings.DATABASES["default"]["NAME"] == "xmuoj_h7"
admin = User.objects.get(username="h7root")
knowledge, _ = KnowledgePoint.objects.get_or_create(code="h7_addition", defaults={
    "name": "H7 加法联调", "normalized_name": "h7 加法联调", "category": "basic", "level": 1,
    "status": "active", "created_by": admin})
case_id = "f7" * 16
directory = Path(settings.DATA_DIR) / "test_case" / case_id
directory.mkdir(exist_ok=True)
(directory / "1.in").write_bytes(b"1 2\n")
(directory / "1.out").write_bytes(b"3\n")
(directory / "info").write_text(json.dumps({"spj": False, "allow_public_test_case_download": False,
    "test_cases": {"1": {"input_name": "1.in", "output_name": "1.out", "input_size": 4,
    "output_size": 2, "stripped_output_md5": hashlib.md5(b"3").hexdigest()}}}))
for path in [directory, *directory.iterdir()]:
    os.chown(path, 900, 903)
    os.chmod(path, 0o710 if path.is_dir() else 0o640)
problem, _ = Problem.objects.get_or_create(_id="H7-ADD", defaults={
    "title": "H7 A+B", "description": "Add two integers", "input_description": "a b", "output_description": "a+b",
    "samples": [{"input": "1 2", "output": "3"}], "test_case_id": case_id, "test_case_score": [],
    "languages": ["Python3"], "template": {}, "time_limit": 3000, "memory_limit": 128,
    "rule_type": "ACM", "difficulty": "Low", "created_by": admin, "visible": True})
ProblemKnowledge.objects.get_or_create(problem=problem, knowledge_point=knowledge,
    defaults={"role": "primary", "weight": 1, "reviewed_by": admin})
print(json.dumps({"problem_id": problem.pk, "knowledge_id": knowledge.pk}))

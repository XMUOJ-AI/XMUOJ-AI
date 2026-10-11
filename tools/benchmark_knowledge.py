#!/usr/bin/env python3
"""Repeatable local HTTP-stack benchmark, restricted to a disposable benchmark DB."""
import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "oj.settings")
import django

django.setup()
from django.conf import settings
from django.test import Client, override_settings
from account.models import User, AdminType, ProblemPermission
from problem.models import Problem
from knowledge.models import KnowledgePoint, KnowledgeDependency, ProblemKnowledge, KnowledgeMappingBatch

if not settings.DATABASES["default"]["NAME"].startswith("xmuoj_benchmark"):
    raise SystemExit("Refusing to seed any database except xmuoj_benchmark*")
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--reuse", action="store_true", help="Measure the already seeded disposable benchmark database")
args = parser.parse_args()
if not args.reuse and Problem.objects.exists():
    raise SystemExit("Benchmark requires an empty disposable database; use --reuse to measure it again")

COUNT = 100000
if not args.reuse:
    admin = User.objects.create(username="bench-admin", admin_type=AdminType.SUPER_ADMIN, problem_permission=ProblemPermission.ALL)
    reviewer = User.objects.create(username="bench-reviewer", admin_type=AdminType.SUPER_ADMIN, problem_permission=ProblemPermission.ALL)
    points = KnowledgePoint.objects.bulk_create([KnowledgePoint(code=f"bench_{i:03}", name=f"Bench {i}", normalized_name=f"bench {i}",
        category="algorithm", level=2, status="active", created_by=admin) for i in range(100)])
    KnowledgeDependency.objects.bulk_create([KnowledgeDependency(prerequisite=points[i-1], dependent=points[i],
        relation_type="required", weight="1", created_by=admin) for i in range(1, 100)])
    for start in range(0, COUNT, 1000):
        problems = Problem.objects.bulk_create([Problem(_id=f"BENCH{i:06}", title=f"Benchmark {i}", description="benchmark",
            input_description="", output_description="", samples=[], test_case_id="benchmark", test_case_score=[],
            languages=["Python3"], template={}, time_limit=1000, memory_limit=128, rule_type="ACM", difficulty="Low", created_by=admin)
            for i in range(start, start + 1000)])
        ProblemKnowledge.objects.bulk_create([ProblemKnowledge(problem=problem, knowledge_point=points[(start+i) % 100],
            role="primary", weight="1", reviewed_by=reviewer) for i, problem in enumerate(problems)])
        KnowledgeMappingBatch.objects.bulk_create([KnowledgeMappingBatch(problem=problem, batch_version=1, base_version=0,
            approved_version=1, status="approved", submitted_by=admin, reviewed_by=reviewer,
            payload=[{"knowledge_code": points[(start+i) % 100].code, "role": "primary", "weight": 1.0}])
            for i, problem in enumerate(problems)])
    pending = KnowledgeMappingBatch.objects.bulk_create([KnowledgeMappingBatch(problem=problem, batch_version=2, base_version=1,
        submitted_by=admin, payload=[{"knowledge_code": points[i % 100].code, "role": "primary", "weight": .5}])
        for i, problem in enumerate(Problem.objects.order_by("id")[:1000])])
else:
    if Problem.objects.count() != COUNT or KnowledgePoint.objects.count() != 100:
        raise SystemExit("Existing database does not match this benchmark fixture")
    reviewer = User.objects.get(username="bench-reviewer")
    pending = list(KnowledgeMappingBatch.objects.filter(status="pending").order_by("id")[:28])
    if len(pending) != 28:
        raise SystemExit("Not enough pending batches for 3 warmups plus 25 measurements")
client = Client()
client.force_login(reviewer)
measurements = {}


def record(name, request, iterations=25):
    values = []
    for index in range(iterations + 3):
        begin = time.perf_counter()
        response = request(index)
        elapsed = (time.perf_counter() - begin) * 1000
        if response.status_code != 200:
            raise RuntimeError(f"{name}: {response.status_code}: {response.content[:200]!r}")
        if index >= 3:
            values.append(elapsed)
    values.sort()
    measurements[name] = {"samples": len(values), "median_ms": round(values[len(values)//2], 2),
                          "p95_ms": round(values[math.ceil(len(values)*.95)-1], 2), "max_ms": round(values[-1], 2)}


with override_settings(DEBUG=False):
    record("admin_list", lambda _: client.get("/api/admin/knowledge-points?page_size=20"))
    record("review_queue", lambda _: client.get("/api/admin/knowledge-reviews?page_size=20"))
    record("graph_depth_3", lambda _: client.get("/api/knowledge-graph?root_code=bench_050&depth=3"))
    record("mapping_approval", lambda index: client.post(f"/api/admin/knowledge-reviews/problem_mapping/{pending[index].pk}/approve",
        json.dumps({"expected_updated_time": pending[index].updated_time.isoformat()}), content_type="application/json"))
result = {"database": settings.DATABASES["default"]["NAME"], "mapping_count": ProblemKnowledge.objects.count(),
          "knowledge_count": KnowledgePoint.objects.count(), "pending_review_count_initial": 1000,
          "scope": "Django HTTP stack + PostgreSQL14 + Redis; loopback, sequential warm requests, excludes browser/network and multi-user load",
          "measurements": measurements}
print(json.dumps(result, ensure_ascii=False, indent=2))

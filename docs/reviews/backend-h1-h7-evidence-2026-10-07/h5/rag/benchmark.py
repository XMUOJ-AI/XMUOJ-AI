"""Isolated, reproducible PostgreSQL RAG query benchmark; never use a production DB."""
import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "oj.settings")

import django  # noqa: E402
django.setup()

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.models import Q  # noqa: E402
from knowledge.tests import make_point, make_user  # noqa: E402
from rag.models import RagChunk, RagDocument  # noqa: E402
from rag.services import eligible_chunks, search  # noqa: E402

OUT = Path(__file__).resolve().parent
QUERIES = {"english_multiword": "binary invariant", "english_phrase": "binary search",
           "chinese_long": "区间不变式", "chinese_three": "不变式", "chinese_two": "变式",
           "chinese_one": "缀", "common_two": "算法", "no_match": "unfindablewordxyz"}


def guard():
    settings = connection.settings_dict
    if settings["NAME"] != "xmuoj_h5" or str(settings["PORT"]) != "15432" or settings["HOST"] not in ("127.0.0.1", "localhost"):
        raise RuntimeError("This script only writes isolated loopback xmuoj_h5 on port 15432")


def seed():
    guard()
    from account.models import User
    from knowledge.models import KnowledgePoint
    actor = User.objects.filter(username="h5_rag_benchmark").first() or make_user("h5_rag_benchmark")
    points = []
    for number in range(20):
        code = "h5_rag_corpus_{}".format(number)
        points.append(KnowledgePoint.objects.filter(code=code).first() or make_point(code, actor))
    if RagDocument.objects.filter(source_id__startswith="h5-rag-corpus-").exists():
        raise RuntimeError("Corpus already exists; re-use it without reseeding")
    paragraphs = (
        "Graph traversal records visited vertices and explores adjacent edges. 图遍历记录已访问结点并分析邻接关系与边的数量。",
        "Dynamic programming uses states and transitions to reuse smaller solutions. 动态规划通过状态转移复用子问题结果并分析算法复杂度。",
        "Sorting algorithms compare keys and exchange elements while preserving required order. 排序过程比较关键字并维护元素顺序。",
        "A queue processes arriving tasks in order; a stack tracks nested tasks. 队列按先后处理任务，栈用于保存嵌套调用的状态。",
        "Hash tables associate keys with values and must handle collisions. 哈希表建立关键字到存储位置的映射并处理冲突。",
    )
    documents, chunks = [], []
    started = time.monotonic()
    for number in range(20000):
        point = points[number % len(points)]
        doc_id = uuid5(NAMESPACE_URL, "xmuoj-h5-rag-doc-{}".format(number))
        metadata = {"knowledge_id": point.pk}
        parts = []
        for part in range(5):
            prefix = ""
            # Each knowledge point has 50 selective chunks among 5,000 scoped chunks.
            if (number // 20) % 100 == 0:
                prefix = "Binary search maintains a shrinking interval invariant. 二分查找维护区间不变式并利用前缀和辅助分析。 "
            body = (prefix + paragraphs[(number + part) % len(paragraphs)] * 12)[:1100]
            body += " example {} part {}".format(number, part)
            parts.append(body)
            chunks.append(RagChunk(id=uuid5(NAMESPACE_URL, "xmuoj-h5-rag-chunk-{}-{}".format(number, part)),
                                   document_id=doc_id, chunk_index=part, content=body,
                                   content_hash=hashlib.sha256(body.encode()).hexdigest(), metadata=metadata))
        content = "\n".join(parts)
        documents.append(RagDocument(id=doc_id, title="课程讲义 {}".format(number % 20), source_type="lecture",
                                     source_id="h5-rag-corpus-{}".format(number), content=content,
                                     content_hash=hashlib.sha256(content.encode()).hexdigest(),
                                     access_scope="student", status="active", metadata=metadata))
        if len(documents) == 200:
            RagDocument.objects.bulk_create(documents)
            RagChunk.objects.bulk_create(chunks, batch_size=500)
            documents, chunks = [], []
    with connection.cursor() as cursor:
        for table in ("rag_document", "rag_chunk", "knowledge_point"):
            cursor.execute("ANALYZE " + table)
        cursor.execute("SELECT version(), current_setting('lc_ctype'), current_setting('shared_buffers')")
        environment = cursor.fetchone()
    result = {"documents": 20000, "chunks": 100000, "knowledge_points": 20, "target_knowledge_id": points[0].pk,
              "scoped_chunks": 5000, "selective_chunks_in_scope": 50, "chunk_chars": "about 1120",
              "corpus": "Deterministic synthetic bilingual programming lecture paragraphs; five topics, 1% selective passages, repeated titles.",
              "seed_seconds": time.monotonic() - started, "environment": environment}
    (OUT / "corpus.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)


def querysets(query, point_id):
    candidates = eligible_chunks(point_id)
    vector = SearchVector("content", config="simple")
    sq = SearchQuery(query, config="simple", search_type="plain")
    ranked = candidates.annotate(rank=SearchRank(vector, sq))
    # Exact pre-change query, including its projected search vector.
    original = ranked.annotate(search_vector=vector).filter(Q(search_vector=sq) | Q(content__icontains=query))
    global_chunks = RagChunk.objects.all()
    global_ids = global_chunks.alias(search_vector=vector).filter(search_vector=sq).values("pk").union(
        global_chunks.filter(content__icontains=query).values("pk"))
    scoped_ids = candidates.alias(search_vector=vector).filter(search_vector=sq).values("pk").union(
        candidates.filter(content__icontains=query).values("pk"))
    return {"original_or": original.order_by("-rank", "id")[:5],
            "global_union": ranked.filter(pk__in=global_ids).order_by("-rank", "id")[:5],
            "scoped_union": ranked.filter(pk__in=scoped_ids).order_by("-rank", "id")[:5]}


def measure(stage, variants, samples, cases):
    guard()
    corpus = json.loads((OUT / "corpus.json").read_text())
    results = {"stage": stage, "samples": samples, "warmups": 1,
               "scope": "Django ORM query over real PostgreSQL; loopback, sequential warm queries, excludes network/provider calls and concurrency.",
               "vm": {"architecture": "QEMU amd64", "cpus": 3, "memory_bytes": 4100120576,
                      "background": "Existing service containers remain running; no scheduled sibling build, test or benchmark during final measurement."},
               "corpus": corpus, "queries": {}}
    with connection.cursor() as cursor:
        if stage == "indexed":
            cursor.execute("SET statement_timeout = '5min'")
            cursor.execute("ANALYZE rag_chunk")
            cursor.execute("ANALYZE rag_document")
        cursor.execute("SET statement_timeout = '30s'")
        cursor.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='rag_chunk' ORDER BY indexname")
        results["indexes"] = cursor.fetchall()
    new_indexes = {"rag_chunk_content_fts_gin", "rag_chunk_content_trgm_gin"}
    present = {name for name, _ in results["indexes"]} & new_indexes
    if stage == "before" and present:
        raise RuntimeError("The before baseline must run before lexical indexes are installed")
    if stage != "before" and present != new_indexes:
        raise RuntimeError("Apply rag.0002_lexical_search_indexes before measuring the indexed queries")
    for name, query in QUERIES.items():
        if name not in cases:
            continue
        result = {"query": query, "variants": {}}
        variants_qs = querysets(query, corpus["target_knowledge_id"])
        for variant in variants:
            qs = variants_qs[variant]
            sql, params = qs.query.sql_with_params()
            with connection.cursor() as cursor:
                for _ in range(1):
                    cursor.execute(sql, params)
                    cursor.fetchall()
                timings = []
                for _ in range(samples):
                    started = time.perf_counter()
                    cursor.execute(sql, params)
                    records = cursor.fetchall()
                    timings.append((time.perf_counter() - started) * 1000)
                columns = [column.name for column in cursor.description]
                rows = [(str(row[columns.index("id")]), float(row[columns.index("rank")])) for row in records]
                cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
                plan = cursor.fetchone()[0]
                rendered = cursor.mogrify(sql, params).decode()
            entry = {"median_ms": statistics.median(timings), "min_ms": min(timings), "max_ms": max(timings),
                     "samples_ms": timings, "rows": rows, "plan": plan}
            if samples >= 15:
                entry["observed_p95_ms"] = sorted(timings)[max(0, int(len(timings) * .95 + .999) - 1)]
            result["variants"][variant] = entry
            (OUT / "{}-{}-{}.sql".format(stage, name, variant)).write_text(rendered + ";\n")
            (OUT / "{}-{}-{}-plan.json".format(stage, name, variant)).write_text(json.dumps(plan, indent=2) + "\n")
            print(stage, name, variant, "median_ms", round(entry["median_ms"], 3),
                  "min/max_ms", round(entry["min_ms"], 3), round(entry["max_ms"], 3), flush=True)
        result["same_rows_and_scores"] = len({json.dumps(value["rows"]) for value in result["variants"].values()}) == 1
        if stage == "final":
            before = json.loads((OUT / "before-results.json").read_text())["queries"][name]["variants"]["original_or"]["rows"]
            actual = search(query, corpus["target_knowledge_id"])
            actual_rows = [[hit["chunk_id"], hit["score"]] for hit in actual["hits"]]
            result["actual_search_rows"] = actual_rows
            result["same_as_before_and_actual_search"] = (
                actual_rows == before == [list(row) for row in result["variants"]["scoped_union"]["rows"]])
            if not result["same_as_before_and_actual_search"]:
                raise AssertionError("Recall/rank changed for " + name)
        results["queries"][name] = result
        (OUT / (stage + "-results.json")).write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("seed", "before", "indexed", "final"))
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--cases", nargs="+", choices=tuple(QUERIES), default=list(QUERIES))
    parser.add_argument("--variants", nargs="+", choices=("original_or", "global_union", "scoped_union"))
    args = parser.parse_args()
    if args.stage == "seed":
        seed()
    else:
        defaults = ("original_or",) if args.stage == "before" else ("original_or", "global_union", "scoped_union")
        variants = args.variants or defaults
        measure(args.stage, variants, args.samples, args.cases)

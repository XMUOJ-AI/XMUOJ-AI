import hashlib
import math
import re
import time
from uuid import UUID

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import connection, transaction
from django.db.models import CharField, Q
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.utils.html import strip_tags

from utils.contract_api import ContractError, transaction_lock
from knowledge.models import KnowledgePoint
from knowledge.services import knowledge_write
from problem.models import Problem
from .adapters import MilvusAdapter, config, embeddings, unavailable, validate_url
from .models import RagChunk, RagDocument


def token_count(text):
    # Declared deterministic lexical tokenizer; not a fabricated provider usage count.
    return len(re.findall(r"[\u3400-\u9fff]|\w+|[^\w\s]", text))


def unsafe_content(text):
    return bool(re.search(
        r"(?is)(#include\s*[<\"]|\bint\s+main\s*\(|if\s+__name__\s*==|\bdef\s+(?:solve|main)\s*\("
        r"|\bclass\s+Solution\b|```(?:cpp|c\+\+|python|java|go|rust)\b|BEGIN [A-Z ]*PRIVATE KEY"
        r"|(?:api[_-]?key|authorization)\s*[:=]\s*[^\s]{8,})", text))


@knowledge_write()
def ingest_document(actor, payload):
    if not actor.is_authenticated or actor.is_disabled or not actor.is_super_admin():
        raise ContractError("AGENT_PERMISSION_DENIED", "仅超级管理员可以导入审核资料", 403)
    allowed = {"title", "source_type", "source_id", "source_url", "content", "access_scope", "status", "metadata"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ContractError("AGENT_INPUT_INVALID", "资料字段不合法")
    required = ("title", "source_type", "source_id", "content")
    if any(not isinstance(payload.get(x), str) or not payload[x].strip() for x in required):
        raise ContractError("AGENT_INPUT_INVALID", "资料缺少标题、来源或正文")
    if len(payload["content"].encode()) > 2 * 1024 * 1024 or len(payload["source_id"]) > 100:
        raise ContractError("AGENT_INPUT_TOO_LARGE", "资料超过大小限制", 413)
    if payload["source_type"] not in ("problem", "textbook", "lecture", "solution", "common_error"):
        raise ContractError("AGENT_INPUT_INVALID", "资料类型不合法")
    scope, status = payload.get("access_scope", "student"), payload.get("status", "pending")
    if scope not in ("public", "student", "teacher", "admin") or status not in ("pending", "active", "disabled"):
        raise ContractError("AGENT_INPUT_INVALID", "资料范围或状态不合法")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict) or set(metadata) - {"problem_id", "knowledge_id", "course_chapter", "algorithm_template", "complexity_target"}:
        raise ContractError("AGENT_INPUT_INVALID", "资料元数据不合法")
    if "problem_id" in metadata and (not isinstance(metadata["problem_id"], str) or not 1 <= len(metadata["problem_id"]) <= 100):
        raise ContractError("AGENT_INPUT_INVALID", "problem_id须为展示编号")
    if "knowledge_id" in metadata and (type(metadata["knowledge_id"]) is not int or metadata["knowledge_id"] < 1):
        raise ContractError("AGENT_INPUT_INVALID", "knowledge_id不合法")
    if "knowledge_id" in metadata and not KnowledgePoint.objects.filter(pk=metadata["knowledge_id"], status="active").exists():
        raise ContractError("AGENT_NOT_FOUND", "知识点不存在或不可用", 404)
    if payload["source_type"] in ("problem", "solution") and "problem_id" not in metadata:
        raise ContractError("AGENT_INPUT_INVALID", "题目资料必须绑定 problem_id")
    if "problem_id" in metadata:
        problems = Problem.objects.filter(_id=metadata["problem_id"], contest__isnull=True)
        if scope in ("public", "student"):
            problems = problems.filter(visible=True)
        if not problems.exists():
            raise ContractError("AGENT_PROBLEM_NOT_FOUND", "题目不存在或不在资料可见范围", 404)
    for key in ("course_chapter", "algorithm_template"):
        if key in metadata and (not isinstance(metadata[key], str) or len(metadata[key]) > 500):
            raise ContractError("AGENT_INPUT_INVALID", "资料元数据类型或长度不合法")
    if "complexity_target" in metadata:
        value = metadata["complexity_target"]
        if (not isinstance(value, dict) or set(value) != {"time", "space"}
                or any(not isinstance(item, str) or not 1 <= len(item) <= 128 for item in value.values())):
            raise ContractError("AGENT_INPUT_INVALID", "complexity_target 必须提供 time/space 字符串")
    source_url = payload.get("source_url")
    if source_url is not None:
        try:
            validate_url(source_url)
        except (ValueError, TypeError):
            raise ContractError("AGENT_INPUT_INVALID", "来源链接须为不含凭据的 HTTP(S) URL") from None
    title = strip_tags(payload["title"]).strip()
    if not title or len(title) > 256:
        raise ContractError("AGENT_INPUT_INVALID", "清洗后的标题须为 1 至 256 字符")
    content = strip_tags(payload["content"]).strip()
    if not content:
        raise ContractError("AGENT_INPUT_INVALID", "清洗后的正文为空")
    if scope in ("public", "student") and (payload["source_type"] == "solution" or unsafe_content(content)
                                           or unsafe_content(title) or unsafe_content(str(metadata))):
        raise ContractError("AGENT_OUTPUT_BLOCKED", "完整解答或敏感资料不能进入学生检索范围", 422)
    digest = hashlib.sha256(content.encode()).hexdigest()
    transaction_lock("rag-source", payload["source_type"] + ":" + payload["source_id"])
    existing = RagDocument.objects.filter(source_type=payload["source_type"], source_id=payload["source_id"], content_hash=digest).first()
    if existing:
        projection_changed = (existing.access_scope, existing.status, existing.metadata) != (scope, status, metadata)
        unchanged = not projection_changed and existing.title == title and existing.source_url == source_url
        existing.title = title
        existing.source_url = source_url
        existing.access_scope = scope
        existing.status = status
        existing.metadata = metadata
        if not unchanged:
            existing.save(update_fields=("title", "source_url", "access_scope", "status", "metadata", "updated_time"))
        if projection_changed:
            existing.chunks.update(metadata=metadata, embedding_id=None, embedding_model=None, embedding_version=None)
        if status == "active":
            RagDocument.objects.filter(source_type=existing.source_type, source_id=existing.source_id).exclude(pk=existing.pk).update(status="disabled")
        return existing, False
    doc = RagDocument.objects.create(title=title, source_type=payload["source_type"], source_id=payload["source_id"],
                                     source_url=source_url, content=content, content_hash=digest,
                                     access_scope=scope, status=status, metadata=metadata)
    # A source update supersedes the old search projection without destroying audit content.
    if status == "active":
        RagDocument.objects.filter(source_type=doc.source_type, source_id=doc.source_id).exclude(pk=doc.pk).update(status="disabled")
    for i, start in enumerate(range(0, len(content), 1000)):
        part = content[start:start + 1200]
        RagChunk.objects.create(document=doc, chunk_index=i, content=part,
                                content_hash=hashlib.sha256(part.encode()).hexdigest(), token_count=token_count(part), metadata=metadata)
    return doc, True


def index_document(document_id, create_collection=False):
    doc = RagDocument.objects.get(pk=document_id)
    adapter = MilvusAdapter()
    if doc.status != "active":
        adapter.delete_document(doc.pk)
        doc.chunks.update(embedding_id=None, embedding_model=None, embedding_version=None)
        return 0
    chunks = list(doc.chunks.order_by("chunk_index"))
    count = 0
    for start in range(0, len(chunks), 32):
        batch = chunks[start:start + 32]
        vectors = embeddings([x.content for x in batch])
        if create_collection and start == 0:
            adapter.create_collection(len(vectors[0]))
        rows = [{"id": str(chunk.pk), "vector": vector, "document_id": str(doc.pk), "content_hash": chunk.content_hash,
                 "knowledge_id": int(doc.metadata.get("knowledge_id", 0)), "problem_id": doc.metadata.get("problem_id", ""),
                 "access_scope": doc.access_scope, "status": doc.status, "embedding_model": config("RAG_EMBEDDING_MODEL"),
                 "embedding_version": config("RAG_EMBEDDING_VERSION", "v1")} for chunk, vector in zip(batch, vectors)]
        adapter.upsert(rows)
        with transaction.atomic():
            current = RagDocument.objects.select_for_update().get(pk=doc.pk)
            if current.updated_time != doc.updated_time:
                raise unavailable("索引期间资料已变化，请重建此资料")
            for chunk in batch:
                chunk.embedding_id = str(chunk.pk)
                chunk.embedding_model = config("RAG_EMBEDDING_MODEL")
                chunk.embedding_version = config("RAG_EMBEDDING_VERSION", "v1")
            RagChunk.objects.bulk_update(batch, ("embedding_id", "embedding_model", "embedding_version"))
        count += len(batch)
    return count


def eligible_chunks(knowledge_id, problem_id=None):
    if type(knowledge_id) is not int or knowledge_id < 1:
        raise ContractError("AGENT_INPUT_INVALID", "knowledge_id不合法")
    if not KnowledgePoint.objects.filter(pk=knowledge_id, status="active").exists():
        raise ContractError("AGENT_NOT_FOUND", "知识点不存在或不可用", 404)
    visible_problems = Problem.objects.filter(contest__isnull=True, visible=True)
    if problem_id is not None and (not isinstance(problem_id, str) or not visible_problems.filter(_id=problem_id).exists()):
        raise ContractError("AGENT_PROBLEM_NOT_FOUND", "题目不存在或无权访问", 404)
    scope = Q(document__metadata__knowledge_id=knowledge_id)
    if problem_id is not None:
        scope |= Q(document__metadata__problem_id=problem_id)
    queryset = RagChunk.objects.filter(scope, document__status="active", document__access_scope__in=("public", "student"))
    queryset = queryset.exclude(document__source_type="solution").annotate(
        bound_problem=KeyTextTransform("problem_id", "document__metadata"),
        bound_knowledge=KeyTextTransform("knowledge_id", "document__metadata"))
    # Revalidate every attached resource, even when the query matched a different
    # metadata key. This also closes stale-index leaks after a problem is hidden.
    active_ids = KnowledgePoint.objects.filter(status="active").annotate(text_id=Cast("pk", CharField())).values("text_id")
    return queryset.filter(Q(bound_problem__isnull=True) | Q(bound_problem__in=visible_problems.values("_id"))).filter(
        Q(bound_knowledge__isnull=True) | Q(bound_knowledge__in=active_ids)).select_related("document")


def search(query, knowledge_id, problem_id=None, timeout=None):
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ContractError("AGENT_INPUT_INVALID", "检索内容须为 1 至 2000 字符")
    query = query.strip()
    budget = 30 if timeout is None else timeout
    if not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget <= 0:
        raise unavailable("检索运行超时")
    deadline = time.monotonic() + budget

    def provider_budget():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise unavailable("检索运行超时")
        return min(15, remaining)

    candidates = eligible_chunks(knowledge_id, problem_id)
    mode = config("RAG_RETRIEVAL_BACKEND", "postgres")
    if mode == "milvus":
        vector = embeddings([query], timeout=provider_budget())[0]
        hits = MilvusAdapter().search(vector, knowledge_id, problem_id, timeout=provider_budget())
        ids = []
        try:
            for hit in hits:
                hit["id"] = str(UUID(str(hit["id"])))
                distance = float(hit.get("distance", 0))
                if not math.isfinite(distance) or not re.fullmatch(r"[0-9a-f]{64}", hit["content_hash"]):
                    raise ValueError()
                ids.append(hit["id"])
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            raise unavailable("向量索引响应格式不合法") from None
        # Even a malicious/stale vector result cannot bypass current SQL permission filters.
        rows = {str(x.pk): x for x in candidates.filter(pk__in=ids, embedding_model=config("RAG_EMBEDDING_MODEL"),
                                                        embedding_version=config("RAG_EMBEDDING_VERSION", "v1"))}
        ranked = []
        seen = set()
        for hit in hits:
            chunk = rows.get(str(hit.get("id")))
            if chunk and chunk.pk not in seen and chunk.content_hash == hit.get("content_hash"):
                ranked.append((chunk, max(0.0, min(1.0, (float(hit.get("distance", 0)) + 1) / 2))))
                seen.add(chunk.pk)
        version = "milvus-" + config("RAG_EMBEDDING_VERSION", "v1")
    elif mode == "postgres":
        if connection.vendor != "postgresql":
            raise unavailable("全文检索需要PostgreSQL")
        sq = SearchQuery(query, config="simple", search_type="plain")
        vector = SearchVector("content", config="simple")
        # The literal branch supports Chinese substrings without claiming vector similarity.
        rows = candidates.annotate(rank=SearchRank(vector, sq), search_vector=vector).filter(Q(search_vector=sq) | Q(content__icontains=query)).order_by("-rank", "id")[:5]
        ranked = [(chunk, min(1.0, float(chunk.rank))) for chunk in rows]
        version = "postgres-fts-lexical-v1"
    else:
        raise unavailable("检索后端未配置")
    return {"hits": [{"chunk_id": str(c.pk), "source_type": c.document.source_type, "title": c.document.title,
                      "excerpt": c.content[:1200], "score": score} for c, score in ranked[:5] if not unsafe_content(c.content)],
            "retrieval_version": version}

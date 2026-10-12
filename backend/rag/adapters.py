"""Real HTTP adapters. No synthetic vectors or model completions are produced."""
import json
import io
import math
import os
import re
import time
from functools import partial
from http.client import HTTPConnection, HTTPSConnection, HTTPResponse
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPHandler, HTTPSHandler, HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from utils.contract_api import ContractError


def config(name, default=""):
    return getattr(settings, name, os.environ.get(name, default))


def unavailable(message="检索或模型服务尚未配置"):
    return ContractError("AGENT_DEPENDENCY_NOT_READY", message, 503, retryable=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DeadlineReader(io.RawIOBase):
    def __init__(self, raw, deadline):
        self.raw = raw
        self.deadline = deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Dependency request deadline exceeded")
        self.raw._sock.settimeout(remaining)
        return self.raw.readinto(buffer)

    def close(self):
        self.raw.close()
        super().close()


class DeadlineResponse(HTTPResponse):
    def __init__(self, *args, deadline, **kwargs):
        super().__init__(*args, **kwargs)
        # Header readline and body read must share the same budget, even for byte-at-a-time peers.
        self.fp = io.BufferedReader(DeadlineReader(self.fp.detach(), deadline))


class DeadlineHandler(HTTPSHandler, HTTPHandler):
    def __init__(self, deadline):
        super().__init__()
        self.deadline = deadline

    def connection(self, connection_type, *args, **kwargs):
        connection = connection_type(*args, **kwargs)
        connection.response_class = partial(DeadlineResponse, deadline=self.deadline)
        return connection

    def http_open(self, request):
        return self.do_open(partial(self.connection, HTTPConnection), request)

    def https_open(self, request):
        return self.do_open(partial(self.connection, HTTPSConnection), request, context=self._context)


def validate_url(url):
    if not isinstance(url, str) or any(ord(char) < 33 for char in url):
        raise ValueError("Invalid URL")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("Invalid URL")
    # Evaluate port as well: urlsplit otherwise defers invalid-port validation.
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise ValueError("Invalid port")
    return parts


def post_json(url, body, token="", timeout=15):
    try:
        validate_url(url)
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(url, json.dumps(body, ensure_ascii=False, allow_nan=False).encode(), headers, method="POST")
    except (ValueError, TypeError, UnicodeError):
        raise unavailable("依赖服务配置或请求不合法") from None
    deadline = time.monotonic() + min(timeout, 30)
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise unavailable("依赖服务请求超时")
        try:
            with build_opener(NoRedirect(), DeadlineHandler(deadline)).open(request, timeout=remaining) as response:
                chunks, size = [], 0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise unavailable("依赖服务请求超时")
                    if response.isclosed():
                        break
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise unavailable("依赖服务响应超过限制")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError()
                return data
        except HTTPError as exc:
            retryable = exc.code in (429, 502, 503, 504)
            exc.close()
        except (URLError, TimeoutError, OSError):
            retryable = True
        except (ValueError, TypeError, UnicodeError):
            retryable = False
        if not retryable or attempt:
            # Never echo provider exceptions/bodies: they may contain secrets.
            raise unavailable("依赖服务暂时不可用") from None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise unavailable("依赖服务请求超时")
        time.sleep(min(0.1, remaining))


def embeddings(texts, timeout=15):
    model = config("RAG_EMBEDDING_MODEL")
    if not model:
        raise unavailable("Embedding 服务未配置")
    response = post_json(config("RAG_EMBEDDING_URL"), {"model": model, "input": texts}, config("RAG_EMBEDDING_API_KEY"), timeout=timeout)
    try:
        rows = sorted(response["data"], key=lambda x: x["index"])
        if any(type(row["index"]) is not int for row in rows) or [row["index"] for row in rows] != list(range(len(texts))):
            raise ValueError()
        vectors = [row["embedding"] for row in rows]
        if len(vectors) != len(texts) or not vectors or not vectors[0]:
            raise ValueError()
        dimension = len(vectors[0])
        if dimension > 65536 or any(not isinstance(v, list) or len(v) != dimension or any(
                isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in v) for v in vectors):
            raise ValueError()
        return vectors
    except (KeyError, TypeError, ValueError, OverflowError):
        raise unavailable("Embedding 服务返回格式不合法") from None


class MilvusAdapter:
    """Milvus REST v2 with scalar filters; SQL permissions are checked again."""
    def __init__(self):
        self.url = config("RAG_MILVUS_URL").rstrip("/")
        self.token = config("RAG_MILVUS_TOKEN")
        self.collection = config("RAG_MILVUS_COLLECTION", "xmuoj_rag")
        try:
            parts = validate_url(self.url)
            if parts.query or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,254}", self.collection):
                raise ValueError()
        except (ValueError, TypeError):
            raise unavailable("Milvus 服务未配置")

    def call(self, operation, body, timeout=15):
        result = post_json(self.url + "/v2/vectordb/" + operation,
                           dict(body, collectionName=self.collection), self.token, timeout=timeout)
        if result.get("code") != 0:
            raise unavailable("向量索引操作未完成")
        return result.get("data")

    def create_collection(self, dimension):
        existing = self.call("collections/has", {})
        if not isinstance(existing, dict) or type(existing.get("has")) is not bool:
            raise unavailable("向量索引响应格式不合法")
        if existing["has"]:
            return
        try:
            return self.call("collections/create", {
                "dimension": dimension, "metricType": "COSINE", "idType": "VarChar",
                "primaryFieldName": "id", "vectorFieldName": "vector", "autoID": False,
                "params": {"max_length": 64, "enableDynamicField": True},
            })
        except ContractError:
            # A concurrent bootstrap or a lost successful response is recoverable.
            if self.call("collections/has", {}) == {"has": True}:
                return
            raise

    def upsert(self, rows):
        return self.call("entities/upsert", {"data": rows})

    def search(self, vector, knowledge_id, problem_id=None, timeout=15):
        if type(knowledge_id) is not int or knowledge_id < 1 or (problem_id is not None and not isinstance(problem_id, str)):
            raise ContractError("AGENT_INPUT_INVALID", "检索范围不合法")
        target = "knowledge_id == " + str(int(knowledge_id))
        if problem_id is not None:
            target += " or problem_id == " + json.dumps(problem_id)
        predicate = ('status == "active" and access_scope in ["public", "student"] and embedding_model == '
                     + json.dumps(config("RAG_EMBEDDING_MODEL")) + " and embedding_version == "
                     + json.dumps(config("RAG_EMBEDDING_VERSION", "v1")) + " and (" + target + ")")
        result = self.call("entities/search", {"data": [vector], "annsField": "vector", "filter": predicate,
                           "limit": 20, "outputFields": ["id", "content_hash"], "searchParams": {"metricType": "COSINE"}}, timeout=timeout)
        if not isinstance(result, list):
            raise unavailable("向量索引响应格式不合法")
        return result

    def delete_document(self, document_id):
        return self.call("entities/delete", {"filter": "document_id == " + json.dumps(str(document_id))})

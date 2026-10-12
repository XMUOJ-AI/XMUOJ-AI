import uuid

from django.contrib.postgres.indexes import GinIndex, OpClass
from django.contrib.postgres.search import SearchVector
from django.db import models
from django.db.models.functions import Upper
from utils.models import JSONField


class RagDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.TextField()
    source_type = models.CharField(max_length=32)
    source_id = models.CharField(max_length=100, null=True)
    source_url = models.TextField(null=True)
    content = models.TextField()
    content_hash = models.CharField(max_length=64)
    access_scope = models.CharField(max_length=16, default="student")
    status = models.CharField(max_length=16, default="pending")
    metadata = JSONField(default=dict)
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rag_document"
        constraints = [
            models.UniqueConstraint(fields=("source_type", "source_id", "content_hash"), name="rag_doc_source_hash_unique"),
            models.CheckConstraint(check=models.Q(status__in=("pending", "active", "disabled")), name="rag_doc_status_valid"),
            models.CheckConstraint(check=models.Q(access_scope__in=("public", "student", "teacher", "admin")), name="rag_doc_scope_valid"),
            models.CheckConstraint(check=models.Q(source_type__in=("problem", "textbook", "lecture", "solution", "common_error")), name="rag_doc_type_valid"),
        ]
        indexes = [models.Index(fields=("source_type", "status")), GinIndex(fields=("metadata",))]


class RagChunk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(RagDocument, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    content = models.TextField()
    content_hash = models.CharField(max_length=64)
    token_count = models.PositiveIntegerField(default=0)
    metadata = JSONField(default=dict)
    embedding_id = models.CharField(max_length=200, null=True, unique=True)
    embedding_model = models.CharField(max_length=100, null=True)
    embedding_version = models.CharField(max_length=32, null=True)
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rag_chunk"
        constraints = [models.UniqueConstraint(fields=("document", "chunk_index"), name="rag_chunk_order_unique")]
        indexes = [
            GinIndex(fields=("metadata",)),
            GinIndex(SearchVector("content", config="simple"), name="rag_chunk_content_fts_gin"),
            GinIndex(OpClass(Upper("content"), name="gin_trgm_ops"), name="rag_chunk_content_trgm_gin"),
        ]

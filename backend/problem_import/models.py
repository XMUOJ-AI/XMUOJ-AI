import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


BATCH_STATUSES = ("uploaded", "validating", "validated", "importing", "imported", "partial", "failed", "cancelled")
PROBLEM_STATUSES = ("pending", "validated", "duplicate", "ready", "importing", "imported", "failed", "skipped")


class ProblemImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_key = models.CharField(max_length=64, unique=True)
    schema_version = models.CharField(max_length=16, default="1.0.0")
    producer = models.CharField(max_length=100)
    source_platforms = models.JSONField(default=list)
    manifest = models.JSONField(default=dict)
    archive_sha256 = models.CharField(max_length=64, unique=True)
    archive_path = models.TextField()
    status = models.CharField(max_length=20, default="uploaded")
    problem_count = models.PositiveIntegerField(default=0)
    valid_count = models.PositiveIntegerField(default=0)
    warning_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_summary = models.JSONField(default=dict)
    issues = models.JSONField(default=list)
    tag_mappings = models.JSONField(default=list)
    commit_operations = models.JSONField(default=dict)
    commit_request = models.JSONField(default=dict)
    command_limits = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)
    validated_time = models.DateTimeField(null=True)
    committed_time = models.DateTimeField(null=True)

    class Meta:
        db_table = "problem_import_batch"
        indexes = [models.Index(fields=("status", "created_time"), name="pib_status_time_idx")]
        constraints = [models.CheckConstraint(check=Q(status__in=BATCH_STATUSES), name="pib_status_valid")]


class CollectedProblem(models.Model):
    batch = models.ForeignKey(ProblemImportBatch, on_delete=models.CASCADE, related_name="problems")
    line_number = models.PositiveIntegerField()
    source_platform = models.CharField(max_length=50)
    source_id = models.CharField(max_length=100)
    source_url = models.TextField(default="")
    title = models.TextField(default="")
    content_hash = models.CharField(max_length=64, db_index=True)
    raw_data = models.JSONField(default=dict)
    standardized_data = models.JSONField(default=dict)
    validation_errors = models.JSONField(default=list)
    duplicate_of = models.ForeignKey("self", null=True, on_delete=models.SET_NULL)
    review_status = models.CharField(max_length=16, default="pending")
    import_status = models.CharField(max_length=16, default="pending")
    allocated_test_case_id = models.CharField(max_length=32, null=True, unique=True)
    imported_problem = models.ForeignKey("problem.Problem", null=True, on_delete=models.PROTECT)
    import_error_code = models.CharField(max_length=64, null=True)
    import_error_message = models.TextField(null=True)
    collected_at = models.DateTimeField()
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "collected_problem"
        ordering = ("line_number", "id")
        indexes = [models.Index(fields=("source_platform", "source_id"), name="cp_source_idx"),
                   models.Index(fields=("batch", "import_status"), name="cp_batch_status_idx")]
        constraints = [
            models.UniqueConstraint(fields=("batch", "line_number"), name="cp_batch_line_unique"),
            models.UniqueConstraint(fields=("batch", "source_platform", "source_id"), name="cp_batch_source_unique"),
            models.CheckConstraint(check=Q(line_number__gte=1), name="cp_line_positive"),
            models.CheckConstraint(check=Q(import_status__in=PROBLEM_STATUSES), name="cp_status_valid"),
            models.CheckConstraint(check=Q(review_status__in=("pending", "approved", "rejected")),
                                   name="cp_review_status_valid"),
            models.CheckConstraint(check=Q(allocated_test_case_id__isnull=True)
                                   | Q(allocated_test_case_id__regex=r"^[1-9a-f][0-9a-f]{31}$"),
                                   name="cp_allocation_format"),
        ]


class ExternalProblemBinding(models.Model):
    source_platform = models.CharField(max_length=50)
    source_id = models.CharField(max_length=100)
    problem = models.ForeignKey("problem.Problem", on_delete=models.PROTECT)
    first_collected_problem = models.ForeignKey(CollectedProblem, on_delete=models.PROTECT,
                                                related_name="first_bindings")
    latest_collected_problem = models.ForeignKey(CollectedProblem, on_delete=models.PROTECT,
                                                 related_name="latest_bindings")
    first_content_hash = models.CharField(max_length=64)
    latest_content_hash = models.CharField(max_length=64, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "external_problem_binding"
        constraints = [
            models.UniqueConstraint(fields=("source_platform", "source_id"), name="epb_source_unique"),
            models.CheckConstraint(check=Q(first_content_hash__regex=r"^[0-9a-f]{64}$")
                                   & Q(latest_content_hash__regex=r"^[0-9a-f]{64}$"), name="epb_hash_format"),
        ]


class ExternalTagMapping(models.Model):
    source_platform = models.CharField(max_length=50)
    source_tag = models.CharField(max_length=128)
    normalized_source_tag = models.CharField(max_length=128)
    unified_tag = models.CharField(max_length=128)
    knowledge_point = models.ForeignKey("knowledge.KnowledgePoint", null=True, on_delete=models.PROTECT)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, default=1)
    status = models.CharField(max_length=16, default="pending")
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "external_tag_mapping"
        indexes = [models.Index(fields=("source_platform", "status"), name="etm_platform_status_idx")]
        constraints = [
            models.UniqueConstraint(fields=("source_platform", "normalized_source_tag"), name="etm_source_unique"),
            models.CheckConstraint(check=Q(confidence__gte=0, confidence__lte=1), name="etm_confidence_range"),
            models.CheckConstraint(check=Q(status__in=("pending", "active", "disabled")), name="etm_status_valid"),
        ]

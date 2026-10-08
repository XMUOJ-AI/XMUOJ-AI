import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from utils.models import JSONField


class KnowledgePoint(models.Model):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    normalized_name = models.CharField(max_length=128, unique=True)
    description = models.TextField(default="")
    category = models.CharField(max_length=32)
    level = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=16, default="draft")
    version = models.PositiveIntegerField(default=1)
    aliases = JSONField(default=list)
    metadata = JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_point"
        constraints = [
            models.CheckConstraint(check=Q(level__gte=1, level__lte=5), name="kp_level_1_5"),
            models.CheckConstraint(check=Q(version__gte=1), name="kp_version_positive"),
        ]


class KnowledgeDependency(models.Model):
    prerequisite = models.ForeignKey(KnowledgePoint, related_name="outgoing_dependencies", on_delete=models.PROTECT)
    dependent = models.ForeignKey(KnowledgePoint, related_name="incoming_dependencies", on_delete=models.PROTECT)
    relation_type = models.CharField(max_length=16)
    weight = models.DecimalField(max_digits=4, decimal_places=3)
    source = models.CharField(max_length=16, default="manual")
    confidence = models.DecimalField(max_digits=4, decimal_places=3, default=1)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_dependency"
        constraints = [
            models.UniqueConstraint(fields=["prerequisite", "dependent"], name="kd_directed_pair_unique"),
            models.CheckConstraint(check=~Q(prerequisite=F("dependent")), name="kd_no_self_loop"),
            models.CheckConstraint(check=Q(weight__gt=0, weight__lte=1), name="kd_weight_range"),
            models.CheckConstraint(check=Q(version__gte=1), name="kd_version_positive"),
        ]


class KnowledgeDependencyChangeRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operation = models.CharField(max_length=16)
    target_dependency = models.ForeignKey(KnowledgeDependency, null=True, on_delete=models.SET_NULL)
    base_version = models.PositiveIntegerField(null=True)
    prerequisite = models.ForeignKey(KnowledgePoint, null=True, related_name="proposed_prerequisites", on_delete=models.PROTECT)
    dependent = models.ForeignKey(KnowledgePoint, null=True, related_name="proposed_dependents", on_delete=models.PROTECT)
    relation_type = models.CharField(max_length=16, null=True)
    weight = models.DecimalField(max_digits=4, decimal_places=3, null=True)
    status = models.CharField(max_length=16, default="pending")
    reason = models.TextField()
    review_reason = models.TextField(default="")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="knowledge_dependency_submissions", on_delete=models.PROTECT)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="knowledge_dependency_reviews", null=True, on_delete=models.PROTECT)
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_dependency_change_request"
        constraints = [
            models.UniqueConstraint(fields=["target_dependency"], condition=Q(status="pending", operation__in=["update", "delete"]), name="kd_one_pending_target"),
            models.UniqueConstraint(fields=["prerequisite", "dependent"], condition=Q(status="pending", operation="create"), name="kd_one_pending_create"),
            models.CheckConstraint(check=Q(weight__isnull=True) | Q(weight__gt=0, weight__lte=1), name="kd_request_weight_range"),
            models.CheckConstraint(check=Q(reviewed_by__isnull=True) | ~Q(reviewed_by=F("submitted_by")), name="kd_no_self_review"),
        ]


class ProblemKnowledge(models.Model):
    problem = models.ForeignKey("problem.Problem", on_delete=models.PROTECT)
    knowledge_point = models.ForeignKey(KnowledgePoint, on_delete=models.PROTECT)
    role = models.CharField(max_length=16)
    weight = models.DecimalField(max_digits=4, decimal_places=3)
    source = models.CharField(max_length=16, default="manual")
    confidence = models.DecimalField(max_digits=4, decimal_places=3, default=1)
    review_status = models.CharField(max_length=16, default="approved")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "problem_knowledge"
        constraints = [
            models.UniqueConstraint(fields=["problem", "knowledge_point"], name="pk_problem_point_unique"),
            models.UniqueConstraint(fields=["problem"], condition=Q(role="primary"), name="pk_one_primary"),
            models.CheckConstraint(check=Q(weight__gt=0, weight__lte=1), name="pk_weight_range"),
            models.CheckConstraint(check=Q(review_status="approved"), name="pk_approved_only"),
        ]


class KnowledgeMappingBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    problem = models.ForeignKey("problem.Problem", on_delete=models.PROTECT)
    batch_version = models.PositiveIntegerField()
    base_version = models.PositiveIntegerField(default=0)
    approved_version = models.PositiveIntegerField(null=True)
    status = models.CharField(max_length=16, default="pending")
    payload = JSONField()
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="knowledge_mapping_submissions", on_delete=models.PROTECT)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="knowledge_mapping_reviews", null=True, on_delete=models.PROTECT)
    reason = models.TextField(default="")
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_mapping_batch"
        constraints = [
            models.UniqueConstraint(fields=["problem", "batch_version"], name="kmb_problem_batch_unique"),
            models.UniqueConstraint(fields=["problem"], condition=Q(status="pending"), name="kmb_one_pending"),
            models.CheckConstraint(check=Q(reviewed_by__isnull=True) | ~Q(reviewed_by=F("submitted_by")), name="kmb_no_self_review"),
        ]


class KnowledgeReviewEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    object_type = models.CharField(max_length=24)
    object_key = models.CharField(max_length=64)
    object_version = models.PositiveIntegerField()
    action = models.CharField(max_length=16)
    reason = models.TextField(default="")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    snapshot = JSONField()
    request_id = models.CharField(max_length=64, db_index=True)
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "knowledge_review_event"
        indexes = [models.Index(fields=["object_type", "object_key", "object_version", "created_time"], name="kre_object_history")]

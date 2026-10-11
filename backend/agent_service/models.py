import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from utils.models import JSONField

SERVICES = ("submission_feedback", "code_explanation", "socratic_hint", "learning_path_explanation")
RUN_STATES = ("queued", "running", "succeeded", "failed", "blocked", "cancelled")


class AgentConversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    problem = models.ForeignKey("problem.Problem", null=True, on_delete=models.SET_NULL)
    service_type = models.CharField(max_length=40, default="socratic_hint")
    status = models.CharField(max_length=16, default="active")
    current_hint_level = models.SmallIntegerField(default=0)
    first_opened_time = models.DateTimeField(auto_now_add=True)
    hint_available_time = models.DateTimeField(null=True)
    last_active_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_conversation"
        constraints = [
            models.CheckConstraint(check=Q(current_hint_level__gte=0, current_hint_level__lte=3), name="agent_hint_level_range"),
            models.CheckConstraint(check=Q(status__in=("active", "closed", "expired")), name="agent_conversation_status"),
            models.UniqueConstraint(fields=("user", "problem", "service_type"), condition=Q(status="active"), name="agent_active_conversation"),
        ]
        indexes = [models.Index(fields=("user", "problem", "status"))]


class AgentRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    service_type = models.CharField(max_length=40)
    problem = models.ForeignKey("problem.Problem", null=True, on_delete=models.PROTECT)
    submission = models.ForeignKey("submission.Submission", null=True, on_delete=models.PROTECT)
    conversation = models.ForeignKey(AgentConversation, null=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, default="queued")
    idempotency_key = models.CharField(max_length=100, null=True)
    request_hash = models.CharField(max_length=64)
    input_hash = models.CharField(max_length=64, db_index=True)
    input_payload = JSONField(default=dict)
    output_payload = JSONField(null=True)
    provider = models.CharField(max_length=50, null=True)
    model_name = models.CharField(max_length=100, null=True)
    prompt_version = models.CharField(max_length=32, default="agent-v1")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    tool_call_count = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(null=True)
    safety_status = models.CharField(max_length=16, default="pending")
    error_code = models.CharField(max_length=64, null=True)
    error_message = models.TextField(null=True)
    error_retryable = models.BooleanField(default=False)
    cached_from = models.ForeignKey("self", null=True, on_delete=models.SET_NULL)
    created_time = models.DateTimeField(auto_now_add=True)
    started_time = models.DateTimeField(null=True)
    finished_time = models.DateTimeField(null=True)

    class Meta:
        db_table = "agent_run"
        constraints = [
            models.UniqueConstraint(fields=("user", "idempotency_key"), name="agent_run_idempotency"),
            models.CheckConstraint(check=Q(service_type__in=SERVICES), name="agent_run_service_valid"),
            models.CheckConstraint(check=Q(status__in=RUN_STATES), name="agent_run_status_valid"),
            models.CheckConstraint(check=Q(safety_status__in=("pending", "passed", "blocked", "redacted")), name="agent_run_safety_valid"),
            models.CheckConstraint(check=~Q(service_type__in=("submission_feedback", "code_explanation")) | Q(submission__isnull=False), name="agent_run_submission_required"),
        ]
        indexes = [models.Index(fields=("user", "created_time")), models.Index(fields=("status", "created_time"))]


class AgentToolCall(models.Model):
    id = models.BigAutoField(primary_key=True)
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="tool_calls")
    sequence = models.PositiveIntegerField()
    tool_name = models.CharField(max_length=64)
    tool_version = models.CharField(max_length=16, default="1.0.0")
    service_type = models.CharField(max_length=40)
    arguments = JSONField(default=dict)
    result_summary = JSONField(default=dict)
    status = models.CharField(max_length=16, default="running")
    duration_ms = models.PositiveIntegerField(null=True)
    error_code = models.CharField(max_length=64, null=True)
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_tool_call"
        constraints = [models.UniqueConstraint(fields=("run", "sequence"), name="agent_tool_sequence_unique")]
        indexes = [models.Index(fields=("tool_name",)), models.Index(fields=("error_code",))]


class ErrorPattern(models.Model):
    code = models.CharField(max_length=64, unique=True)
    problem = models.ForeignKey("problem.Problem", null=True, on_delete=models.SET_NULL)
    knowledge_point = models.ForeignKey("knowledge.KnowledgePoint", null=True, on_delete=models.SET_NULL)
    verdict = models.CharField(max_length=20)
    cause_short = models.TextField()
    cause_detail = models.TextField(default="")
    fix_direction = models.TextField()
    retrieval_text = models.TextField(default="")
    priority = models.SmallIntegerField(default=100)
    review_status = models.CharField(max_length=16, default="pending")
    embedding_id = models.CharField(max_length=200, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="created_error_patterns")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="reviewed_error_patterns")
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "error_pattern"
        constraints = [models.CheckConstraint(check=Q(problem__isnull=False) | Q(knowledge_point__isnull=False), name="error_pattern_target_required")]
        indexes = [models.Index(fields=("problem", "verdict", "review_status"))]


class AgentMessage(models.Model):
    id = models.BigAutoField(primary_key=True)
    conversation = models.ForeignKey(AgentConversation, on_delete=models.CASCADE, related_name="messages")
    sequence = models.PositiveIntegerField()
    role = models.CharField(max_length=16)
    content = models.TextField()
    metadata = JSONField(default=dict)
    token_count = models.PositiveIntegerField(default=0)
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_message"
        constraints = [models.UniqueConstraint(fields=("conversation", "sequence"), name="agent_message_sequence_unique")]


class AIFeedbackReview(models.Model):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    rating = models.CharField(max_length=24)
    comment = models.TextField(default="")
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_feedback_review"
        constraints = [models.UniqueConstraint(fields=("run", "user"), name="agent_feedback_unique")]


class AgentDispatch(models.Model):
    """Durable queue intent; broker outages never discard a committed run."""
    run = models.OneToOneField(AgentRun, primary_key=True, on_delete=models.CASCADE)
    delivered_time = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_dispatch"

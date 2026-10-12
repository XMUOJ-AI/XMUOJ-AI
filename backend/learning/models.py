import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Q

USER = settings.AUTH_USER_MODEL
MASTERY = ("unknown", "weak", "learning", "stable", "mastered")


class TeachingClass(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    course_name = models.CharField(max_length=128, default="")
    term = models.CharField(max_length=32, default="")
    status = models.CharField(max_length=16, default="active")
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT)
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "teaching_class"
        constraints = [models.CheckConstraint(check=Q(status__in=("draft", "active", "archived")), name="tc_status_valid")]


class TeachingClassTeacher(models.Model):
    teaching_class = models.ForeignKey(TeachingClass, on_delete=models.PROTECT, related_name="teachers")
    teacher = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="teaching_memberships")
    role = models.CharField(max_length=16, default="teacher")
    status = models.CharField(max_length=16, default="active")
    granted_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="granted_teaching_memberships")
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "teaching_class_teacher"
        constraints = [
            models.UniqueConstraint(fields=("teaching_class", "teacher"), name="tct_member_unique"),
            models.CheckConstraint(check=Q(role__in=("owner", "teacher", "assistant")), name="tct_role_valid"),
            models.CheckConstraint(check=Q(status__in=("active", "disabled")), name="tct_status_valid"),
        ]


class TeachingClassStudent(models.Model):
    teaching_class = models.ForeignKey(TeachingClass, on_delete=models.PROTECT, related_name="students")
    student = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="class_memberships")
    student_number = models.CharField(max_length=64, null=True)
    status = models.CharField(max_length=16, default="active")
    joined_time = models.DateTimeField(auto_now_add=True)
    left_time = models.DateTimeField(null=True)

    class Meta:
        db_table = "teaching_class_student"
        constraints = [
            models.UniqueConstraint(fields=("teaching_class", "student"), name="tcs_member_unique"),
            models.UniqueConstraint(fields=("teaching_class", "student_number"), condition=Q(student_number__isnull=False), name="tcs_number_unique"),
            models.CheckConstraint(check=Q(status__in=("active", "left")), name="tcs_status_valid"),
        ]


class StudentKnowledgeState(models.Model):
    user = models.ForeignKey(USER, on_delete=models.PROTECT)
    knowledge_point = models.ForeignKey("knowledge.KnowledgePoint", on_delete=models.PROTECT)
    rating = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1200"))
    mastery_level = models.CharField(max_length=16, default="unknown")
    attempt_count = models.PositiveIntegerField(default=0)
    accepted_count = models.PositiveIntegerField(default=0)
    recent_fail_count = models.PositiveIntegerField(default=0)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, default=Decimal("0"))
    algorithm_version = models.CharField(max_length=32, default="elo-v1")
    last_submission_time = models.DateTimeField(null=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "student_knowledge_state"
        constraints = [
            models.UniqueConstraint(fields=("user", "knowledge_point"), name="sks_user_knowledge_unique"),
            models.CheckConstraint(check=Q(rating__gte=0), name="sks_rating_nonnegative"),
            models.CheckConstraint(check=Q(confidence__gte=0, confidence__lte=1), name="sks_confidence_range"),
            models.CheckConstraint(check=Q(accepted_count__lte=F("attempt_count")), name="sks_accepted_count_valid"),
            models.CheckConstraint(check=Q(mastery_level__in=MASTERY), name="sks_mastery_valid"),
        ]


class ProblemKnowledgeRating(models.Model):
    problem = models.ForeignKey("problem.Problem", on_delete=models.PROTECT)
    knowledge_point = models.ForeignKey("knowledge.KnowledgePoint", on_delete=models.PROTECT)
    rating = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1200"))
    source = models.CharField(max_length=16, default="difficulty")
    attempt_count = models.PositiveIntegerField(default=0)
    accepted_count = models.PositiveIntegerField(default=0)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, default=Decimal("0"))
    algorithm_version = models.CharField(max_length=32, default="elo-v1")
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "problem_knowledge_rating"
        constraints = [
            models.UniqueConstraint(fields=("problem", "knowledge_point"), name="pkr_pair_unique"),
            models.CheckConstraint(check=Q(rating__gte=0), name="pkr_rating_nonnegative"),
            models.CheckConstraint(check=Q(confidence__gte=0, confidence__lte=1), name="pkr_confidence_range"),
            models.CheckConstraint(check=Q(accepted_count__lte=F("attempt_count")), name="pkr_counts_valid"),
            models.CheckConstraint(check=Q(source__in=("difficulty", "statistics", "manual")), name="pkr_source_valid"),
        ]


class RatingHistory(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(USER, on_delete=models.PROTECT)
    knowledge_point = models.ForeignKey("knowledge.KnowledgePoint", on_delete=models.PROTECT)
    problem = models.ForeignKey("problem.Problem", on_delete=models.PROTECT)
    submission = models.ForeignKey("submission.Submission", on_delete=models.PROTECT)
    old_rating = models.DecimalField(max_digits=10, decimal_places=4)
    new_rating = models.DecimalField(max_digits=10, decimal_places=4)
    delta = models.DecimalField(max_digits=10, decimal_places=4)
    problem_rating = models.DecimalField(max_digits=10, decimal_places=4)
    expected_score = models.DecimalField(max_digits=7, decimal_places=6)
    actual_score = models.DecimalField(max_digits=7, decimal_places=6)
    result = models.IntegerField()
    result_weight = models.DecimalField(max_digits=5, decimal_places=4)
    algorithm_version = models.CharField(max_length=32, default="elo-v1")
    calculation_detail = models.JSONField(default=dict)
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rating_history"
        constraints = [
            models.UniqueConstraint(fields=("submission", "knowledge_point", "algorithm_version"), name="rh_submission_knowledge_version"),
            models.CheckConstraint(check=Q(expected_score__gte=0, expected_score__lte=1, actual_score__gte=0,
                                   actual_score__lte=1, result_weight__gte=0, result_weight__lte=1), name="rh_score_range"),
        ]


class LearningPath(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(USER, on_delete=models.PROTECT)
    target_knowledge = models.ForeignKey("knowledge.KnowledgePoint", null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, default="active")
    algorithm_version = models.CharField(max_length=32, default="path-v1")
    input_snapshot = models.JSONField(default=dict)
    reason_summary = models.JSONField(default=dict)
    generated_time = models.DateTimeField(auto_now_add=True)
    expires_time = models.DateTimeField(null=True)

    class Meta:
        db_table = "learning_path"
        constraints = [
            models.UniqueConstraint(fields=("user",), condition=Q(status="active"), name="lp_one_active_per_user"),
            models.CheckConstraint(check=Q(status__in=("active", "completed", "expired", "superseded")), name="lp_status_valid"),
        ]


class LearningPathStep(models.Model):
    learning_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, related_name="steps")
    step_order = models.PositiveIntegerField()
    knowledge_point = models.ForeignKey("knowledge.KnowledgePoint", on_delete=models.PROTECT)
    problem = models.ForeignKey("problem.Problem", null=True, on_delete=models.SET_NULL)
    problem_rating = models.DecimalField(max_digits=10, decimal_places=4, null=True)
    reason_code = models.CharField(max_length=32)
    reason_text = models.CharField(max_length=1000)
    status = models.CharField(max_length=16, default="pending")

    class Meta:
        db_table = "learning_path_step"
        ordering = ("step_order",)
        constraints = [
            models.UniqueConstraint(fields=("learning_path", "step_order"), name="lps_order_unique"),
            models.CheckConstraint(check=Q(step_order__gt=0), name="lps_order_positive"),
            models.CheckConstraint(check=Q(status__in=("pending", "in_progress", "completed", "skipped")), name="lps_status_valid"),
        ]


class LearningRefreshRequest(models.Model):
    user = models.ForeignKey(USER, on_delete=models.PROTECT)
    key = models.CharField(max_length=100)
    fingerprint = models.CharField(max_length=64)
    response = models.JSONField()
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "learning_refresh_request"
        constraints = [models.UniqueConstraint(fields=("user", "key"), name="lrr_user_key_unique")]


class TeachingAccessEvent(models.Model):
    actor = models.ForeignKey(USER, on_delete=models.PROTECT)
    teaching_class = models.ForeignKey(TeachingClass, on_delete=models.PROTECT)
    student_id = models.PositiveIntegerField(null=True)
    reason = models.CharField(max_length=1000)
    request_id = models.CharField(max_length=64)
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "teaching_access_event"


class LearningSubmissionEvent(models.Model):
    # Durable outbox and immutable input snapshots for deterministic rejudge replay.
    submission = models.OneToOneField("submission.Submission", on_delete=models.PROTECT)
    user = models.ForeignKey(USER, on_delete=models.PROTECT)
    fingerprint = models.CharField(max_length=64)
    payload = models.JSONField()
    revision = models.PositiveIntegerField(default=1)
    processed_revision = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, default="pending", db_index=True)
    error_code = models.CharField(max_length=64, default="")
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "learning_submission_event"

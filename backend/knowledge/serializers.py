"""Strict request validation and explicit, separate public/admin projections."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from .models import CATEGORIES


def normalize_name(value):
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    return value.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected a JSON object")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "Unknown field" for key in sorted(unknown)})
        return super().to_internal_value(data)


class StrictInteger(serializers.IntegerField):
    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, int):
            raise serializers.ValidationError("Expected an integer")
        return super().to_internal_value(data)


class StrictString(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError("Expected a string")
        return super().to_internal_value(data)


class CodeField(StrictString):
    def __init__(self, **kwargs):
        super().__init__(max_length=64, trim_whitespace=False, **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value):
            raise serializers.ValidationError("Invalid knowledge code")
        return value


class WeightField(serializers.Field):
    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (int, float, Decimal)):
            raise serializers.ValidationError("Expected a number")
        try:
            value = Decimal(str(data))
            valid = value.is_finite() and 0 < value <= 1 and value % Decimal("0.001") == 0
        except (InvalidOperation, ValueError):
            valid = False
        if not valid:
            raise serializers.ValidationError("Weight must be in (0, 1] in increments of 0.001")
        return value

    def to_representation(self, value):
        return float(value)


class MetadataInput(StrictSerializer):
    course_chapter = StrictString(max_length=128, allow_blank=True, trim_whitespace=False, required=False)
    display_order = StrictInteger(min_value=0, required=False)


class KnowledgeCreateInput(StrictSerializer):
    code = CodeField()
    name = StrictString(min_length=1, max_length=128, trim_whitespace=False)
    description = StrictString(max_length=5000, allow_blank=True, trim_whitespace=False)
    category = serializers.ChoiceField(choices=CATEGORIES)
    level = StrictInteger(min_value=1, max_value=5)
    aliases = serializers.ListField(child=StrictString(min_length=1, max_length=128, trim_whitespace=False),
                                    max_length=20, required=False)
    metadata = MetadataInput(required=False)

    def validate_name(self, value):
        normalized = normalize_name(value)
        if not normalized or len(normalized) > 128:
            raise serializers.ValidationError("Normalized name must contain 1 to 128 characters")
        return value

    def validate_aliases(self, values):
        seen, result = set(), []
        for value in values:
            normalized = normalize_name(value)
            if not normalized or len(normalized) > 128:
                raise serializers.ValidationError("Normalized aliases must contain 1 to 128 characters")
            if normalized not in seen:
                seen.add(normalized)
                result.append(value)
        return result


class KnowledgeUpdateInput(KnowledgeCreateInput):
    code = None
    version = StrictInteger(min_value=1)
    status = serializers.ChoiceField(choices=("draft", "active", "deprecated"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "version":
                field.required = False

    def validate(self, data):
        if len(data) < 2:
            raise serializers.ValidationError("At least one editable field is required")
        return data


class DeleteInput(StrictSerializer):
    version = StrictInteger(min_value=1)
    reason = StrictString(min_length=2, max_length=500)


class DependencyChangeInput(StrictSerializer):
    operation = serializers.ChoiceField(choices=("create", "update", "delete"))
    reason = StrictString(min_length=2, max_length=500)
    target_dependency_id = StrictInteger(min_value=1, required=False)
    base_version = StrictInteger(min_value=1, required=False)
    prerequisite_code = CodeField(required=False)
    dependent_code = CodeField(required=False)
    relation_type = serializers.ChoiceField(choices=("required", "recommended"), required=False)
    weight = WeightField(required=False)

    def validate(self, data):
        expected = {"operation", "reason"}
        if data["operation"] in ("update", "delete"):
            expected |= {"target_dependency_id", "base_version"}
        if data["operation"] in ("create", "update"):
            expected |= {"prerequisite_code", "dependent_code", "relation_type", "weight"}
        if set(data) != expected:
            raise serializers.ValidationError({"fields": "Fields do not match operation", "required": sorted(expected)})
        return data


class MappingInput(StrictSerializer):
    knowledge_code = CodeField()
    role = serializers.ChoiceField(choices=("primary", "secondary", "prerequisite"))
    weight = WeightField()


class MappingSetInput(StrictSerializer):
    base_version = StrictInteger(min_value=0)
    mappings = MappingInput(many=True, min_length=1, max_length=20)


class ReviewInput(StrictSerializer):
    expected_updated_time = serializers.DateTimeField()

    def validate_expected_updated_time(self, value):
        raw = self.initial_data["expected_updated_time"]
        if not isinstance(raw, str) or not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", raw):
            raise serializers.ValidationError("An ISO 8601 timestamp with timezone is required")
        return value


class RejectInput(ReviewInput):
    reason = StrictString(min_length=2, max_length=500)


def user_summary(user):
    return {"id": user.id, "username": user.username} if user else None


def point_data(point):
    fields = ("id", "code", "name", "normalized_name", "description", "category", "level", "status",
              "version", "aliases", "metadata")
    return dict({key: getattr(point, key) for key in fields},
                created_by=user_summary(point.created_by),
                created_time=point.created_time.isoformat(), updated_time=point.updated_time.isoformat())


def dependency_data(edge):
    return {"id": edge.id, "prerequisite": point_data(edge.prerequisite), "dependent": point_data(edge.dependent),
            "relation_type": edge.relation_type, "weight": float(edge.weight), "source": edge.source,
            "confidence": float(edge.confidence), "version": edge.version, "updated_time": edge.updated_time.isoformat()}


def dependency_state(edge):
    return {"prerequisite_code": edge.prerequisite.code, "dependent_code": edge.dependent.code,
            "relation_type": edge.relation_type, "weight": float(edge.weight), "source": edge.source,
            "confidence": float(edge.confidence), "version": edge.version, "updated_time": edge.updated_time.isoformat()}


def change_data(change):
    return {"request_id": str(change.id), "operation": change.operation,
            "target_dependency_id": change.target_dependency_id, "original_target_id": change.original_target_id,
            "base_version": change.base_version, "before": change.before, "proposed": change.proposed,
            "status": change.status, "reason": change.reason, "review_reason": change.review_reason,
            "submitted_by": user_summary(change.submitted_by), "reviewed_by": user_summary(change.reviewed_by),
            "created_time": change.created_time.isoformat(), "updated_time": change.updated_time.isoformat()}


def batch_data(batch):
    return {"review_batch_id": str(batch.id), "problem_id": batch.problem_id, "batch_version": batch.batch_version,
            "base_version": batch.base_version, "approved_version": batch.approved_version, "status": batch.status,
            "mappings": batch.payload, "reason": batch.reason, "updated_time": batch.updated_time.isoformat()}


def problem_summary(problem):
    return {"problem_id": problem.id, "display_id": problem._id, "title": problem.title}

"""Explicit local administration entry point until class management has an HTTP contract."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from account.models import User
from learning.models import TeachingAccessEvent, TeachingClass, TeachingClassStudent, TeachingClassTeacher
from utils.contract_api import ContractSerializer, transaction_lock


class TeacherInput(ContractSerializer):
    username = serializers.CharField(max_length=150)
    role = serializers.ChoiceField(choices=("owner", "teacher", "assistant"), default="teacher")
    status = serializers.ChoiceField(choices=("active", "disabled"), default="active")


class StudentInput(ContractSerializer):
    username = serializers.CharField(max_length=150)
    student_number = serializers.CharField(max_length=64, allow_null=True, required=False)
    status = serializers.ChoiceField(choices=("active", "left"), default="active")


class ClassInput(ContractSerializer):
    code = serializers.RegexField(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    name = serializers.CharField(max_length=128)
    course_name = serializers.CharField(max_length=128, default="", allow_blank=True)
    term = serializers.CharField(max_length=32)
    status = serializers.ChoiceField(choices=("draft", "active", "archived"), default="active")
    teachers = TeacherInput(many=True, default=list)
    students = StudentInput(many=True, default=list)


class Command(BaseCommand):
    help = "Merge a reviewed JSON class roster; omitted members are preserved. Requires an administrator or active class owner and audit reason."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        actor = User.objects.filter(username=options["actor"], is_disabled=False).first()
        if actor is None:
            raise CommandError("An active actor is required")
        reason = options["reason"].strip()
        if not reason or len(reason) > 1000:
            raise CommandError("Audit reason must contain 1 to 1000 characters")
        try:
            value = json.loads(Path(options["file"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise CommandError("Cannot read a valid JSON roster") from None
        serializer = ClassInput(data=value)
        if not serializer.is_valid():
            raise CommandError("Invalid roster fields: " + ", ".join(serializer.errors))
        data = dict(serializer.validated_data)
        teachers, students = data.pop("teachers"), data.pop("students")
        for members in (teachers, students):
            names = [member["username"] for member in members]
            if len(names) != len(set(names)):
                raise CommandError("Duplicate member in roster")
        usernames = {member["username"] for member in teachers + students}
        users = {user.username: user for user in User.objects.filter(username__in=usernames, is_disabled=False)}
        if set(users) != usernames:
            raise CommandError("Roster contains unknown or disabled users")
        transaction_lock("teaching_class", data["code"])
        klass = TeachingClass.objects.filter(code=data["code"]).first()
        if not actor.is_admin_role():
            if klass is None or klass.status != "active" or not klass.teachers.filter(
                    teacher=actor, role="owner", status="active").exists():
                raise CommandError("An administrator or active owner of this class is required")
            if any(getattr(klass, key) != item for key, item in data.items() if key in value):
                raise CommandError("Class owners may merge members but cannot change class fields")
        else:
            if klass is None:
                klass = TeachingClass.objects.create(**data, created_by=actor)
            else:
                for key, item in data.items():
                    setattr(klass, key, item)
                klass.save()
        for member in teachers:
            TeachingClassTeacher.objects.update_or_create(teaching_class=klass, teacher=users[member["username"]],
                                                          defaults={"role": member["role"], "status": member["status"], "granted_by": actor})
        for member in students:
            defaults = {"status": member["status"], "left_time": timezone.now() if member["status"] == "left" else None}
            if "student_number" in member:
                defaults["student_number"] = member["student_number"]
            if defaults.get("student_number") and klass.students.filter(student_number=defaults["student_number"]).exclude(student=users[member["username"]]).exists():
                raise CommandError("Student number already belongs to another member")
            TeachingClassStudent.objects.update_or_create(teaching_class=klass, student=users[member["username"]], defaults=defaults)
        TeachingAccessEvent.objects.create(actor=actor, teaching_class=klass, reason="Roster update: " + reason[:985], request_id="management-command")
        self.stdout.write(f"Updated class {klass.code} ({klass.pk}); merged {len(teachers)} teachers and {len(students)} students")

import re
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from account.models import AdminType, ProblemPermission, User
from problem.models import Problem

from .models import (KnowledgeDependency, KnowledgeDependencyChangeRequest, KnowledgeMappingBatch,
                     KnowledgePoint, KnowledgeReviewEvent, ProblemKnowledge)


def seed(*args):
    out = StringIO()
    call_command("seed_knowledge_demo", *args, stdout=out)
    return out.getvalue()


def baseline():
    return {
        "active": KnowledgePoint.objects.filter(status="active").count(),
        "draft": KnowledgePoint.objects.filter(status="draft").count(),
        "deprecated": KnowledgePoint.objects.filter(status="deprecated").count(),
        "dependencies": KnowledgeDependency.objects.count(),
        "problems": Problem.objects.filter(_id__startswith="DEMO").count(),
        "mapped_problems": ProblemKnowledge.objects.values("problem").distinct().count(),
        "pending_dependency": KnowledgeDependencyChangeRequest.objects.filter(status="pending").count(),
        "rejected_dependency": KnowledgeDependencyChangeRequest.objects.filter(status="rejected").count(),
        "pending_mapping": KnowledgeMappingBatch.objects.filter(status="pending").count(),
        "users": User.objects.count(),
        "events": KnowledgeReviewEvent.objects.count(),
    }


class SeedKnowledgeDemoTests(TestCase):
    def test_refuses_outside_debug(self):
        with self.assertRaisesMessage(CommandError, "DEBUG"):
            seed()
        self.assertFalse(User.objects.exists())
        self.assertFalse(KnowledgePoint.objects.exists())

    @override_settings(DEBUG=True)
    def test_builds_checklist_baseline_once_with_random_passwords(self):
        output = seed()
        counts = baseline()
        self.assertEqual({key: counts[key] for key in counts if key not in ("users", "events")},
                         {"active": 14, "draft": 1, "deprecated": 1, "dependencies": 12, "problems": 3,
                          "mapped_problems": 2, "pending_dependency": 1, "rejected_dependency": 1, "pending_mapping": 1})
        passwords = dict(re.findall(r"^\s*(demo_\w+)\s+(\S+)\s*$", output, re.M))
        self.assertEqual(set(passwords), {"demo_student", "demo_reviewer", "demo_approver",
                                          "demo_admin_all", "demo_admin_own", "demo_admin_none"})
        self.assertEqual(len(set(passwords.values())), 6)
        for username, password in passwords.items():
            self.assertTrue(User.objects.get(username=username).check_password(password))
        # Formal data went through submit + review, so every change has audit events.
        self.assertTrue(KnowledgeReviewEvent.objects.filter(action="approved").exists())

        rerun = seed()
        self.assertEqual(baseline(), counts)
        self.assertFalse(re.search(r"^\s*demo_\w+\s+\S+\s*$", rerun, re.M))
        self.assertTrue(User.objects.get(username="demo_student").check_password(passwords["demo_student"]))

        reset = dict(re.findall(r"^\s*(demo_\w+)\s+(\S+)\s*$", seed("--reset-passwords"), re.M))
        self.assertEqual(set(reset), set(passwords))
        self.assertFalse(User.objects.get(username="demo_student").check_password(passwords["demo_student"]))
        self.assertTrue(User.objects.get(username="demo_student").check_password(reset["demo_student"]))

    @override_settings(DEBUG=True)
    def test_refuses_to_change_existing_account_with_other_role(self):
        user = User.objects.create(username="Demo_Reviewer", admin_type=AdminType.REGULAR_USER,
                                   problem_permission=ProblemPermission.NONE)
        with self.assertRaisesMessage(CommandError, "Demo_Reviewer"):
            seed()
        user.refresh_from_db()
        self.assertEqual(user.admin_type, AdminType.REGULAR_USER)
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(KnowledgePoint.objects.exists())

    @override_settings(DEBUG=True)
    def test_refuses_to_take_over_existing_problem(self):
        owner = User.objects.create(username="teacher", admin_type=AdminType.SUPER_ADMIN)
        Problem.objects.create(_id="DEMO1000", title="real", description="", input_description="", output_description="",
                               samples=[], test_case_id="real", test_case_score=[], languages=["C++"], template={},
                               time_limit=1000, memory_limit=128, rule_type="ACM", difficulty="Low", created_by=owner)
        with self.assertRaisesMessage(CommandError, "DEMO1000"):
            seed()
        self.assertFalse(KnowledgeMappingBatch.objects.exists())
        self.assertEqual(User.objects.count(), 1)

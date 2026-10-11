import io
import os
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from account.models import AdminType, User, UserProfile


class BootstrapAdminTests(TestCase):
    def bootstrap(self, **environment):
        with patch.dict(os.environ, environment, clear=True):
            call_command("inituser", action="bootstrap", stdout=io.StringIO())

    def test_empty_database_requires_explicit_password(self):
        with self.assertRaisesMessage(CommandError, "DJANGO_SUPERUSER_PASSWORD"):
            self.bootstrap()
        self.assertFalse(User.objects.exists())

    def test_environment_password_is_preserved_literally(self):
        password = "isolated-test-'quote-$literal"
        self.bootstrap(DJANGO_SUPERUSER_USERNAME="initial-admin", DJANGO_SUPERUSER_PASSWORD=password)
        user = User.objects.get(username="initial-admin")
        self.assertEqual(user.admin_type, AdminType.SUPER_ADMIN)
        self.assertTrue(user.check_password(password))
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_existing_administrator_needs_no_password_and_is_not_overwritten(self):
        self.bootstrap(DJANGO_SUPERUSER_PASSWORD="initial-test-password")
        user = User.objects.get(username="root")
        previous_hash = user.password
        self.bootstrap()
        self.bootstrap(DJANGO_SUPERUSER_PASSWORD="another-test-password")
        user.refresh_from_db()
        self.assertEqual(user.password, previous_hash)
        self.assertEqual(User.objects.count(), 1)

    def test_bootstrap_does_not_promote_existing_normal_account(self):
        user = User.objects.create(username="root")
        with self.assertRaisesMessage(CommandError, "another account"):
            self.bootstrap(DJANGO_SUPERUSER_PASSWORD="isolated-test-password")
        user.refresh_from_db()
        self.assertEqual(user.admin_type, AdminType.REGULAR_USER)
        self.assertFalse(UserProfile.objects.exists())

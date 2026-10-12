import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from account.models import AdminType, ProblemPermission, User, UserProfile
from utils.contract_api import transaction_lock


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--username", type=str)
        parser.add_argument("--password", type=str)
        parser.add_argument("--action", type=str)

    def handle(self, *args, **options):
        username = options["username"]
        password = options["password"]
        action = options["action"]

        if action == "bootstrap":
            # Read secrets inside Python, never from shell interpolation or argv.
            username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "root")
            password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
            with transaction.atomic():
                transaction_lock("deployment_bootstrap", "superuser")
                if User.objects.filter(admin_type=AdminType.SUPER_ADMIN).exists():
                    self.stdout.write("An administrator already exists; bootstrap skipped")
                    return
                if not username or not password:
                    raise CommandError("Set DJANGO_SUPERUSER_PASSWORD before the first startup")
                if User.objects.filter(username=username).exists():
                    raise CommandError("Bootstrap username already belongs to another account; choose DJANGO_SUPERUSER_USERNAME")
                user = User(username=username, admin_type=AdminType.SUPER_ADMIN, problem_permission=ProblemPermission.ALL)
                user.set_password(password)
                user.save()
                UserProfile.objects.create(user=user)
            self.stdout.write(self.style.SUCCESS("Administrator created"))
            return

        if not (username and password and action):
            self.stdout.write(self.style.ERROR("Invalid args"))
            exit(1)

        if action == "create_super_admin":
            if User.objects.filter(id=1).exists():
                self.stdout.write(self.style.SUCCESS(f"User {username} exists, operation ignored"))
                exit()

            user = User.objects.create(username=username, admin_type=AdminType.SUPER_ADMIN,
                                       problem_permission=ProblemPermission.ALL)
            user.set_password(password)
            user.save()
            UserProfile.objects.create(user=user)

            self.stdout.write(self.style.SUCCESS("User created"))
        elif action == "reset":
            try:
                user = User.objects.get(username=username)
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS("Password is rested"))
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"User {username} doesnot exist, operation ignored"))
                exit(1)
        else:
            raise ValueError("Invalid action")

import secrets
import string

from django.db import connection, transaction, IntegrityError
from django.db.models import Q
from django.db.models.functions import Upper
from django.http import HttpResponse
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from submission.models import Submission
from utils.api import APIError, APIView, validate_serializer
from utils.contract_api import transaction_lock
from utils.shortcuts import rand_str

from ..decorators import super_admin_required
from ..models import AdminType, ProblemPermission, User, UserProfile, UserCredentialExport
from ..credential_exports import (cleanup_expired_exports, create_export, export_metadata, read_export,
                                  remove_export_file, request_digest, EXPORT_ID_PATTERN)
from ..serializers import EditUserSerializer, UserAdminSerializer, GenerateUserSerializer, ChangeUserpasswordSerializer
from ..serializers import ImportUserSeralizer, BatchResetPasswordSerializer


def bulk_username_matches(usernames):
    """Use PostgreSQL's UPPER comparison, exactly as the login iexact lookup does."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT UPPER(name) FROM unnest(%s::text[]) WITH ORDINALITY AS names(name, position) ORDER BY position",
                       [usernames])
        keys = [row[0] for row in cursor.fetchall()]
    if len(set(keys)) != len(keys):
        raise APIError("Duplicate usernames in import")
    existing = {}
    for user in User.objects.select_for_update().annotate(login_key=Upper("username")).filter(login_key__in=keys).order_by("id"):
        if user.login_key in existing:
            raise APIError("Multiple existing accounts match the same login; no users were changed")
        existing[user.login_key] = user
    return {name: existing[key] for name, key in zip(usernames, keys) if key in existing}


class UserAdminAPI(APIView):
    @sensitive_variables()
    @validate_serializer(ImportUserSeralizer)
    @super_admin_required
    def post(self, request):
        """Import students; repeat requests recover the same private export."""
        data = request.data["users"]
        for user_data in data:
            if len(user_data) != 3 or len(user_data[0]) > 32:
                return self.error("Each row must contain a username (at most 32 characters), name and classroom")
        if not data:
            return self.error("empty user list")
        original_digest = request_digest(data)
        data = [[row[0].lower(), row[1], row[2]] for row in data]
        if any(len(row[0]) > 32 for row in data):
            return self.error("Username should not more than 32 characters")
        if len({row[0] for row in data}) != len(data):
            return self.error("Duplicate usernames in import")

        created_export = None
        try:
            cleanup_expired_exports()
            with transaction.atomic():
                # A shared creation lock also covers absent names across different
                # administrators; historical mixed-case rows remain unchanged.
                transaction_lock("account_bulk_creation", "usernames")
                User.objects.select_for_update().get(pk=request.user.pk)
                digest = request_digest(data)
                existing = bulk_username_matches([row[0] for row in data])
                receipt = UserCredentialExport.objects.filter(
                    created_by=request.user, operation="import", request_digest__in=[digest, original_digest],
                    expires_at__gt=timezone.now()).order_by("-created_at").first()
                if receipt:
                    return self.success(export_metadata(receipt))
                new_rows, credentials = [], []
                for username, real_name, classroom in data:
                    if username in existing:
                        profile = UserProfile.objects.get(user=existing[username])
                        profile.school = classroom
                        profile.save(update_fields=["school"])
                    else:
                        new_rows.append((username, real_name, classroom))
                        credentials.append((username, secrets.token_urlsafe(18)))
                users = User.objects.bulk_create([
                    User(username=username, password=make_password(password)) for username, password in credentials])
                UserProfile.objects.bulk_create([
                    UserProfile(user=user, real_name=row[1], school=row[2], language="zh-CN")
                    for user, row in zip(users, new_rows)
                ])
                if credentials:
                    created_export = create_export(request.user, "import", digest, credentials, len(existing))
                    result = export_metadata(created_export)
                else:
                    result = {"file_id": None, "created_count": 0, "updated_count": len(existing), "expires_at": None}
            return self.success(result)
        except Exception as error:
            if created_export:
                remove_export_file(created_export.id)
            if isinstance(error, IntegrityError):
                return self.error("Import conflicted with another account change; no users were changed, please retry")
            if isinstance(error, OSError):
                return self.error("Credential export unavailable; no users were changed, please retry")
            raise

    @validate_serializer(EditUserSerializer)
    @super_admin_required
    def put(self, request):
        """
        Edit user api
        """
        data = request.data
        try:
            user = User.objects.get(id=data["id"])
        except User.DoesNotExist:
            return self.error("User does not exist")
        if User.objects.filter(username=data["username"].lower()).exclude(id=user.id).exists():
            return self.error("Username already exists")
        if data.get("email"):
            if User.objects.filter(email=data["email"].lower()).exclude(id=user.id).exists():
                return self.error("Email already exists")

        pre_username = user.username
        user.username = data["username"].lower()
        user.email = data["email"].lower() if data.get("email") else None
        user.admin_type = data["admin_type"]
        user.is_disabled = data["is_disabled"]

        if data["admin_type"] == AdminType.ADMIN:
            user.problem_permission = data["problem_permission"]
        elif data["admin_type"] == AdminType.SUPER_ADMIN:
            user.problem_permission = ProblemPermission.ALL
        else:
            user.problem_permission = ProblemPermission.NONE

        if data["password"]:
            user.set_password(data["password"])

        if data["open_api"]:
            # Avoid reset user appkey after saving changes
            if not user.open_api:
                user.open_api_appkey = rand_str()
        else:
            user.open_api_appkey = None
        user.open_api = data["open_api"]

        if data["two_factor_auth"]:
            # Avoid reset user tfa_token after saving changes
            if not user.two_factor_auth:
                user.tfa_token = rand_str()
        else:
            user.tfa_token = None

        user.two_factor_auth = data["two_factor_auth"]

        user.save()
        if pre_username != user.username:
            Submission.objects.filter(username=pre_username).update(username=user.username)

        UserProfile.objects.filter(user=user).update(real_name=data["real_name"])
        return self.success(UserAdminSerializer(user).data)

    @super_admin_required
    def get(self, request):
        """
        User list api / Get user by id
        """
        user_id = request.GET.get("id")
        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return self.error("User does not exist")
            return self.success(UserAdminSerializer(user).data)

        user = User.objects.all().order_by("-create_time")

        keyword = request.GET.get("keyword", None)
        if keyword:
            user = user.filter(Q(username__icontains=keyword) |
                               Q(userprofile__real_name__icontains=keyword) |
                               Q(email__icontains=keyword))
        return self.success(self.paginate_data(request, user, UserAdminSerializer))

    @super_admin_required
    def delete(self, request):
        id = request.GET.get("id")
        if not id:
            return self.error("Invalid Parameter, id is required")
        ids = id.split(",")
        if str(request.user.id) in ids:
            return self.error("Current user can not be deleted")
        User.objects.filter(id__in=ids).delete()
        return self.success()


class GenerateUserAPI(APIView):
    @super_admin_required
    def get(self, request):
        """List the creator's active exports or download one, without consuming it."""
        cleanup_expired_exports()
        exports = UserCredentialExport.objects.filter(created_by=request.user, expires_at__gt=timezone.now())
        if request.GET.get("list") == "1":
            response = self.success([export_metadata(export) for export in exports.order_by("-created_at")[:100]])
        else:
            file_id = request.GET.get("file_id", "")
            if not EXPORT_ID_PATTERN.fullmatch(file_id):
                return self.error("Credential export unavailable or expired")
            export = exports.filter(pk=file_id).first()
            if export is None:
                return self.error("Credential export unavailable or expired")
            try:
                raw_data = read_export(export)
            except OSError:
                return self.error("Credential export unavailable or expired")
            response = HttpResponse(raw_data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            response["Content-Disposition"] = "attachment; filename=users.xlsx"
        response["Cache-Control"] = "no-store, private"
        response["Pragma"] = "no-cache"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @sensitive_variables()
    @validate_serializer(GenerateUserSerializer)
    @super_admin_required
    def post(self, request):
        original_digest = request_digest(request.data)
        data = dict(request.data, prefix=request.data["prefix"].lower(), suffix=request.data["suffix"].lower())
        number_max_length = max(len(str(data["number_from"])), len(str(data["number_to"])))
        if number_max_length + len(data["prefix"]) + len(data["suffix"]) > 32:
            return self.error("Username should not more than 32 characters")
        if data["number_from"] > data["number_to"]:
            return self.error("Start number must be lower than end number")

        created_export = None
        try:
            cleanup_expired_exports()
            with transaction.atomic():
                transaction_lock("account_bulk_creation", "usernames")
                User.objects.select_for_update().get(pk=request.user.pk)
                digest = request_digest(data)
                usernames = [f"{data['prefix']}{number}{data['suffix']}" for number in range(data["number_from"], data["number_to"] + 1)]
                existing = bulk_username_matches(usernames)
                receipt = UserCredentialExport.objects.filter(
                    created_by=request.user, operation="generate", request_digest__in=[digest, original_digest],
                    expires_at__gt=timezone.now()).order_by("-created_at").first()
                if receipt:
                    return self.success(export_metadata(receipt))
                if existing:
                    return self.error("Username already exists; no users were created")
                credentials = [(username, "".join(
                    secrets.choice(string.ascii_letters + string.digits) for _ in range(data["password_length"])))
                    for username in usernames]
                users = User.objects.bulk_create([
                    User(username=username, password=make_password(password)) for username, password in credentials])
                UserProfile.objects.bulk_create([UserProfile(user=user) for user in users])
                created_export = create_export(request.user, "generate", digest, credentials)
            return self.success(export_metadata(created_export))
        except Exception as error:
            if created_export:
                remove_export_file(created_export.id)
            if isinstance(error, IntegrityError):
                return self.error("Username already exists; no users were created")
            if isinstance(error, OSError):
                return self.error("Credential export unavailable; no users were created, please retry")
            raise


class ChangeUserpasswordAPI(APIView):
    @validate_serializer(ChangeUserpasswordSerializer)
    @super_admin_required
    def post(self, request):
        data = request.data
        suffix = data["suffix"]
        match_type = data["match_type"]
        right_length = data["right_length"]
        target_name = data["target_name"]

        if match_type == "type_username":
            try:
                for user in User.objects.filter(username__contains=target_name):
                    newpass = suffix
                    if right_length > 0:
                        newpass = user.username[-right_length:] + suffix
                    user.set_password(newpass)
                    user.save()
                return self.success()
            except IntegrityError as e:
                return self.error(str(e).split("\n")[1])
        else:
            try:
                for userprofile in UserProfile.objects.filter(school__contains=target_name):
                    user = userprofile.user
                    newpass = suffix
                    if right_length > 0:
                        newpass = user.username[-right_length:] + suffix
                    user.set_password(newpass)
                    user.save()
                return self.success()
            except IntegrityError as e:
                return self.error(str(e).split("\n")[1])


class BatchResetPasswordAPI(APIView):
    @validate_serializer(BatchResetPasswordSerializer)
    @super_admin_required
    def post(self, request):
        """
        远程批量重置密码: 给定学号列表 + 固定密码
        POST /api/admin/batch_reset_password/
        body: {"users": ["学号1","学号2",...], "password": "新密码"}
        """
        data = request.data
        usernames = data["users"]
        new_password = data["password"]

        ok = 0
        missing = []

        for username in usernames:
            try:
                user = User.objects.get(username=username)
                user.set_password(new_password)
                user.save()
                ok += 1
            except User.DoesNotExist:
                missing.append(username)

        result = {"updated": ok, "missing": missing}
        return self.success(result)

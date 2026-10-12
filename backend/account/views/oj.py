import logging
import os
from datetime import timedelta
from importlib import import_module

import qrcode
from django.conf import settings
from django.contrib import auth
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.utils.timezone import now
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from otpauth import OtpAuth

from contest.models import Contest, ACMContestRank, OIContestRank, ContestParticipation
from problem.models import Problem
from submission.models import JudgeStatus
from utils.constants import ContestRuleType, ContestStatus
from options.options import SysOptions
from utils.api import APIView, validate_serializer, CSRFExemptAPIView
from utils.captcha import Captcha
from utils.shortcuts import rand_str, img2base64, datetime2str
from ..decorators import login_required, check_contest_permission
from ..models import User, UserProfile, AdminType
from ..serializers import (ApplyResetPasswordSerializer, ResetPasswordSerializer,
                           UserChangePasswordSerializer, UserLoginSerializer,
                           UserRegisterSerializer, UsernameOrEmailCheckSerializer,
                           RankInfoSerializer, UserChangeEmailSerializer, SSOSerializer)
from ..serializers import (TwoFactorAuthCodeSerializer, UserProfileSerializer,
                           EditUserProfileSerializer, ImageUploadForm)
from ..tasks import send_email_async

logger = logging.getLogger(__name__)


class UserProfileAPI(APIView):
    @method_decorator(ensure_csrf_cookie)
    def get(self, request, **kwargs):
        """
        判断是否登录， 若登录返回用户信息
        """
        user = request.user
        if not user.is_authenticated:
            return self.success()
        show_real_name = False
        username = request.GET.get("username")
        try:
            if username:
                user = User.objects.get(username=username, is_disabled=False)
            else:
                user = request.user
                # api返回的是自己的信息，可以返real_name
                show_real_name = True
        except User.DoesNotExist:
            return self.error("User does not exist")
        # Non-SuperAdmin users may only view their own profile
        if username and request.user.is_authenticated and username != request.user.username:
            if request.user.admin_type != AdminType.SUPER_ADMIN:
                return self.error("Permission denied")
        return self.success(UserProfileSerializer(user.userprofile, show_real_name=show_real_name).data)

    @validate_serializer(EditUserProfileSerializer)
    @login_required
    def put(self, request):
        data = request.data
        user_profile = request.user.userprofile
        for k, v in data.items():
            setattr(user_profile, k, v)
        user_profile.save()
        return self.success(UserProfileSerializer(user_profile, show_real_name=True).data)


class AvatarUploadAPI(APIView):
    request_parsers = ()

    @login_required
    def post(self, request):
        form = ImageUploadForm(request.POST, request.FILES)
        if form.is_valid():
            avatar = form.cleaned_data["image"]
        else:
            return self.error("Invalid file content")
        if avatar.size > 2 * 1024 * 1024:
            return self.error("Picture is too large")
        suffix = os.path.splitext(avatar.name)[-1].lower()
        if suffix not in [".gif", ".jpg", ".jpeg", ".bmp", ".png"]:
            return self.error("Unsupported file format")

        name = rand_str(10) + suffix
        with open(os.path.join(settings.AVATAR_UPLOAD_DIR, name), "wb") as img:
            for chunk in avatar:
                img.write(chunk)
        user_profile = request.user.userprofile

        user_profile.avatar = f"{settings.AVATAR_URI_PREFIX}/{name}"
        user_profile.save()
        return self.success("Succeeded")


class TwoFactorAuthAPI(APIView):
    @login_required
    def get(self, request):
        """
        Get QR code
        """
        user = request.user
        if user.two_factor_auth:
            return self.error("2FA is already turned on")
        token = rand_str()
        user.tfa_token = token
        user.save()

        label = f"{SysOptions.website_name_shortcut}:{user.username}"
        image = qrcode.make(OtpAuth(token).to_uri("totp", label, SysOptions.website_name.replace(" ", "")))
        return self.success(img2base64(image))

    @login_required
    @validate_serializer(TwoFactorAuthCodeSerializer)
    def post(self, request):
        """
        Open 2FA
        """
        code = request.data["code"]
        user = request.user
        if OtpAuth(user.tfa_token).valid_totp(code):
            user.two_factor_auth = True
            user.save()
            return self.success("Succeeded")
        else:
            return self.error("Invalid code")

    @login_required
    @validate_serializer(TwoFactorAuthCodeSerializer)
    def put(self, request):
        code = request.data["code"]
        user = request.user
        if not user.two_factor_auth:
            return self.error("2FA is already turned off")
        if OtpAuth(user.tfa_token).valid_totp(code):
            user.two_factor_auth = False
            user.save()
            return self.success("Succeeded")
        else:
            return self.error("Invalid code")


class CheckTFARequiredAPI(CSRFExemptAPIView):
    @validate_serializer(UsernameOrEmailCheckSerializer)
    def post(self, request):
        """
        Check TFA is required
        """
        data = request.data
        result = False
        if data.get("username"):
            try:
                user = User.objects.get(username=data["username"])
                result = user.two_factor_auth
            except User.DoesNotExist:
                pass
        return self.success({"result": result})


class UserLoginAPI(CSRFExemptAPIView):
    @validate_serializer(UserLoginSerializer)
    def post(self, request):
        """
        User login api
        """
        data = request.data
        user = auth.authenticate(username=data["username"], password=data["password"])
        # None is returned if username or password is wrong
        if user:
            if user.is_disabled:
                return self.error("Your account has been disabled")
            if not user.two_factor_auth:
                auth.login(request, user)
                return self.success("Succeeded")

            # `tfa_code` not in post data
            if user.two_factor_auth and "tfa_code" not in data:
                return self.error("tfa_required")

            if OtpAuth(user.tfa_token).valid_totp(data["tfa_code"]):
                auth.login(request, user)
                return self.success("Succeeded")
            else:
                return self.error("Invalid two factor verification code")
        else:
            return self.error("Invalid username or password")


class UserLogoutAPI(APIView):
    def get(self, request):
        auth.logout(request)
        return self.success()


class UsernameOrEmailCheck(APIView):
    @validate_serializer(UsernameOrEmailCheckSerializer)
    def post(self, request):
        """
        check username or email is duplicate
        """
        data = request.data
        # True means already exist.
        result = {
            "username": False,
            "email": False
        }
        if data.get("username"):
            result["username"] = User.objects.filter(username=data["username"].lower()).exists()
        if data.get("email"):
            result["email"] = User.objects.filter(email=data["email"].lower()).exists()
        return self.success(result)


class UserRegisterAPI(APIView):
    @validate_serializer(UserRegisterSerializer)
    def post(self, request):
        """
        User register api
        """
        if not SysOptions.allow_register:
            return self.error("Register function has been disabled by admin")

        data = request.data
        data["username"] = data["username"].lower()
        data["email"] = data["email"].lower()
        captcha = Captcha(request)
        if not captcha.check(data["captcha"]):
            return self.error("Invalid captcha")
        if User.objects.filter(username=data["username"]).exists():
            return self.error("Username already exists")
        if User.objects.filter(email=data["email"]).exists():
            return self.error("Email already exists")
        user = User.objects.create(username=data["username"], email=data["email"])
        user.set_password(data["password"])
        user.save()
        UserProfile.objects.create(user=user)
        return self.success("Succeeded")


class UserChangeEmailAPI(APIView):
    @validate_serializer(UserChangeEmailSerializer)
    @login_required
    def post(self, request):
        data = request.data
        user = auth.authenticate(username=request.user.username, password=data["password"])
        if user:
            if user.two_factor_auth:
                if "tfa_code" not in data:
                    return self.error("tfa_required")
                if not OtpAuth(user.tfa_token).valid_totp(data["tfa_code"]):
                    return self.error("Invalid two factor verification code")
            data["new_email"] = data["new_email"].lower()
            if User.objects.filter(email=data["new_email"]).exists():
                return self.error("The email is owned by other account")
            user.email = data["new_email"]
            user.save()
            return self.success("Succeeded")
        else:
            return self.error("Wrong password")


class UserChangePasswordAPI(APIView):
    @validate_serializer(UserChangePasswordSerializer)
    @login_required
    def post(self, request):
        """
        User change password api
        """
        data = request.data
        username = request.user.username
        user = auth.authenticate(username=username, password=data["old_password"])
        if user:
            if user.two_factor_auth:
                if "tfa_code" not in data:
                    return self.error("tfa_required")
                if not OtpAuth(user.tfa_token).valid_totp(data["tfa_code"]):
                    return self.error("Invalid two factor verification code")
            user.set_password(data["new_password"])
            user.save()
            return self.success("Succeeded")
        else:
            return self.error("Invalid old password")


class ApplyResetPasswordAPI(APIView):
    @validate_serializer(ApplyResetPasswordSerializer)
    def post(self, request):
        if request.user.is_authenticated:
            return self.error("You have already logged in, are you kidding me? ")
        data = request.data
        captcha = Captcha(request)
        if not captcha.check(data["captcha"]):
            return self.error("Invalid captcha")
        try:
            user = User.objects.get(email__iexact=data["email"])
        except User.DoesNotExist:
            return self.error("User does not exist")
        if user.reset_password_token_expire_time and 0 < int(
                (user.reset_password_token_expire_time - now()).total_seconds()) < 20 * 60:
            return self.error("You can only reset password once per 20 minutes")
        user.reset_password_token = rand_str()
        user.reset_password_token_expire_time = now() + timedelta(minutes=20)
        user.save()
        render_data = {
            "username": user.username,
            "website_name": SysOptions.website_name,
            "link": f"{SysOptions.website_base_url}/reset-password/{user.reset_password_token}"
        }
        email_html = render_to_string("reset_password_email.html", render_data)
        admin_email = SysOptions.smtp_config.get("email", "") if SysOptions.smtp_config else ""
        send_email_async.send(from_name=SysOptions.website_name_shortcut,
                              to_email=admin_email,
                              to_name=user.username,
                              subject=f"Reset password request: {user.username}",
                              content=email_html)
        return self.success("Succeeded")


class ResetPasswordAPI(APIView):
    @validate_serializer(ResetPasswordSerializer)
    def post(self, request):
        data = request.data
        captcha = Captcha(request)
        if not captcha.check(data["captcha"]):
            return self.error("Invalid captcha")
        try:
            user = User.objects.get(reset_password_token=data["token"])
        except User.DoesNotExist:
            return self.error("Token does not exist")
        if user.reset_password_token_expire_time < now():
            return self.error("Token has expired")
        user.reset_password_token = None
        user.two_factor_auth = False
        user.set_password(data["password"])
        user.save()
        return self.success("Succeeded")


class SessionManagementAPI(APIView):
    @login_required
    def get(self, request):
        engine = import_module(settings.SESSION_ENGINE)
        session_store = engine.SessionStore
        current_session = request.session.session_key
        session_keys = request.user.session_keys
        result = []
        expired_keys = []
        for key in session_keys[:]:
            session = session_store(key)
            # session does not exist or is expiry
            if not session._session:
                expired_keys.append(key)
                continue

            s = {}
            if current_session == key:
                s["current_session"] = True
            s["ip"] = session["ip"]
            s["user_agent"] = session["user_agent"]
            s["last_activity"] = datetime2str(session["last_activity"])
            s["session_key"] = key
            result.append(s)
        if expired_keys:
            with transaction.atomic():
                user = User.objects.select_for_update().only("session_keys").get(pk=request.user.pk)
                user.session_keys = [key for key in user.session_keys if key not in expired_keys]
                user.save(update_fields=["session_keys"])
        return self.success(result)

    @login_required
    def delete(self, request):
        session_key = request.GET.get("session_key")
        if not session_key:
            return self.error("Parameter Error")
        with transaction.atomic():
            user = User.objects.select_for_update().only("session_keys").get(pk=request.user.pk)
            if session_key not in user.session_keys:
                return self.error("Invalid session_key")
            user.session_keys.remove(session_key)
            user.save(update_fields=["session_keys"])
            if session_key == request.session.session_key:
                auth.logout(request)
            else:
                request.session.delete(session_key)
        return self.success("Succeeded")


class UserRankAPI(APIView):
    def get(self, request):
        rule_type = request.GET.get("rule")
        if rule_type not in ContestRuleType.choices():
            rule_type = ContestRuleType.ACM
        profiles = UserProfile.objects.filter(user__admin_type=AdminType.REGULAR_USER, user__is_disabled=False) \
            .select_related("user")
        if rule_type == ContestRuleType.ACM:
            profiles = profiles.filter(submission_number__gt=0).order_by("-accepted_number", "submission_number")
        else:
            profiles = profiles.filter(total_score__gt=0).order_by("-total_score")
        return self.success(self.paginate_data(request, profiles, RankInfoSerializer))


class ProfileProblemDisplayIDRefreshAPI(APIView):
    @login_required
    def get(self, request):
        from submission.models import JudgeStatus

        profile = request.user.userprofile
        acm_root = profile.acm_problems_status or {}
        oi_root = profile.oi_problems_status or {}
        acm_problems = acm_root.get("problems", {}) or {}
        oi_problems = oi_root.get("problems", {}) or {}

        ids = []
        ids.extend([str(i) for i in acm_problems.keys()])
        ids.extend([str(i) for i in oi_problems.keys()])

        if not ids:
            return self.success({"removed": 0, "accepted_number": profile.accepted_number, "total_score": profile.total_score})

        valid_rows = Problem.objects.filter(
            id__in=ids,
            contest_id__isnull=True,
            visible=True
        ).values("id", "_id")
        valid_map = {str(row["id"]): row["_id"] for row in valid_rows}

        new_acm = {}
        for pid, item in acm_problems.items():
            spid = str(pid)
            display_id = valid_map.get(spid)
            if not display_id or not isinstance(item, dict):
                continue
            new_item = dict(item)
            new_item["_id"] = display_id
            new_acm[spid] = new_item

        new_oi = {}
        for pid, item in oi_problems.items():
            spid = str(pid)
            display_id = valid_map.get(spid)
            if not display_id or not isinstance(item, dict):
                continue
            new_item = dict(item)
            new_item["_id"] = display_id
            new_item["score"] = int(new_item.get("score", 0) or 0)
            new_oi[spid] = new_item

        acm_accepted = sum(1 for item in new_acm.values() if item.get("status") == JudgeStatus.ACCEPTED)
        oi_accepted = sum(1 for item in new_oi.values() if item.get("status") == JudgeStatus.ACCEPTED)
        total_score = sum(item.get("score", 0) for item in new_oi.values())

        old_count = len(acm_problems) + len(oi_problems)
        new_count = len(new_acm) + len(new_oi)

        acm_root["problems"] = new_acm
        oi_root["problems"] = new_oi
        profile.acm_problems_status = acm_root
        profile.oi_problems_status = oi_root
        profile.accepted_number = acm_accepted + oi_accepted
        profile.total_score = total_score
        profile.save(update_fields=["acm_problems_status", "oi_problems_status", "accepted_number", "total_score"])

        return self.success({
            "removed": max(old_count - new_count, 0),
            "accepted_number": profile.accepted_number,
            "total_score": profile.total_score
        })


class UserContestSummaryAPI(APIView):
    """
    Read contest projections maintained by durable-verdict scoring and explicit historical rebuilds.
    """

    @staticmethod
    def _get_target_user(request):
        username = request.GET.get("username")
        if not username and request.user.is_authenticated:
            return request.user
        if not username:
            raise User.DoesNotExist
        return User.objects.get(username=username, is_disabled=False)

    @staticmethod
    def _acm_rank_position(contest, rank):
        better_count = ACMContestRank.objects.filter(
            contest=contest,
            user__admin_type=AdminType.REGULAR_USER,
            user__is_disabled=False
        ).filter(
            Q(accepted_number__gt=rank.accepted_number) |
            Q(accepted_number=rank.accepted_number, total_time__lt=rank.total_time)
        ).count()
        return better_count + 1

    @staticmethod
    def _oi_rank_position(contest, rank):
        better_count = OIContestRank.objects.filter(
            contest=contest,
            user__admin_type=AdminType.REGULAR_USER,
            user__is_disabled=False,
            total_score__gt=rank.total_score
        ).count()
        return better_count + 1

    @login_required
    def get(self, request):
        if not request.GET.get("username") and not request.user.is_authenticated:
            return self.error("Please login first", "permission-denied")
        # Only SuperAdmin can query other users' contest history
        if request.GET.get("username") and request.user.is_authenticated:
            if request.GET["username"] != request.user.username:
                if request.user.admin_type != AdminType.SUPER_ADMIN:
                    return self.error("Permission denied")
        try:
            target_user = self._get_target_user(request)
        except User.DoesNotExist:
            return self.error("User does not exist")

        try:
            offset = max(int(request.GET.get("offset", 0)), 0)
            limit = max(int(request.GET.get("limit", 20)), 1)
        except ValueError:
            return self.error("Parameter error")

        participations = list(ContestParticipation.objects.filter(user=target_user)
                              .values("contest_id", "submission_number", "accepted_number", "total_score"))
        participation_map = {item["contest_id"]: item for item in participations}

        # Keep backward compatibility for historical data that may have rank rows
        # but no participation rows yet.
        acm_ranks = list(ACMContestRank.objects.filter(user=target_user).values(
            "contest_id", "submission_number", "accepted_number", "total_time"
        ))
        oi_ranks = list(OIContestRank.objects.filter(user=target_user).values(
            "contest_id", "submission_number", "total_score", "submission_info"
        ))

        acm_rank_map = {item["contest_id"]: item for item in acm_ranks}
        oi_rank_map = {item["contest_id"]: item for item in oi_ranks}
        contest_ids = set(participation_map) | set(acm_rank_map) | set(oi_rank_map)

        contests = Contest.objects.filter(id__in=contest_ids, visible=True).order_by("-end_time", "-id")
        if not request.user.is_super_admin():
            current_time = now()
            contests = contests.exclude(
                Q(rule_type=ContestRuleType.OI, real_time_rank=False,
                  start_time__lte=current_time, end_time__gte=current_time) & ~Q(created_by=request.user))
        total = contests.count()
        contests = list(contests[offset: offset + limit])

        results = []
        for contest in contests:
            item = {
                "contest_id": contest.id,
                "contest_title": contest.title,
                "rule_type": contest.rule_type,
                "start_time": datetime2str(contest.start_time),
                "end_time": datetime2str(contest.end_time),
                "my_rank": None,
                "submission_count": 0,
                "ac_count": 0,
                "total_score": 0
            }
            participation = participation_map.get(contest.id)
            if participation:
                item["submission_count"] = participation["submission_number"]
                item["ac_count"] = participation["accepted_number"]
                item["total_score"] = participation["total_score"]

            if contest.rule_type == ContestRuleType.ACM:
                rank_data = acm_rank_map.get(contest.id)
                if rank_data:
                    rank = ACMContestRank(
                        contest_id=contest.id,
                        user_id=target_user.id,
                        submission_number=rank_data["submission_number"],
                        accepted_number=rank_data["accepted_number"],
                        total_time=rank_data["total_time"]
                    )
                    item["my_rank"] = self._acm_rank_position(contest, rank)
                    item["submission_count"] = rank_data["submission_number"]
                    item["ac_count"] = rank_data["accepted_number"]
            else:
                rank_data = oi_rank_map.get(contest.id)
                if rank_data:
                    rank = OIContestRank(
                        contest_id=contest.id,
                        user_id=target_user.id,
                        submission_number=rank_data["submission_number"],
                        total_score=rank_data["total_score"]
                    )
                    item["my_rank"] = self._oi_rank_position(contest, rank)
                    item["total_score"] = rank_data["total_score"]
                    item["submission_count"] = rank_data["submission_number"]
            results.append(item)

        return self.success({"total": total, "results": results})


class UserContestDetailAPI(APIView):
    """
    Contest/experiment detail for a user. All per-problem status is derived from
    ACMContestRank.submission_info or OIContestRank.submission_info JSON fields.
    ACM submission_info format: {"<problem_id>": {"is_ac": bool, "ac_time": int, "error_number": int}}
    OI  submission_info format: {"<problem_id>": <score_int>}
    Scores come from rank projections; AC flags use eligible durable verdicts.
    """

    @staticmethod
    def _get_target_user(request):
        username = request.GET.get("username")
        if not username and request.user.is_authenticated:
            return request.user
        if not username:
            raise User.DoesNotExist
        return User.objects.get(username=username, is_disabled=False)

    @staticmethod
    def _acm_rank_position(contest, rank):
        better_count = ACMContestRank.objects.filter(
            contest=contest,
            user__admin_type=AdminType.REGULAR_USER,
            user__is_disabled=False
        ).filter(
            Q(accepted_number__gt=rank.accepted_number) |
            Q(accepted_number=rank.accepted_number, total_time__lt=rank.total_time)
        ).count()
        return better_count + 1

    @staticmethod
    def _oi_rank_position(contest, rank):
        better_count = OIContestRank.objects.filter(
            contest=contest,
            user__admin_type=AdminType.REGULAR_USER,
            user__is_disabled=False,
            total_score__gt=rank.total_score
        ).count()
        return better_count + 1

    @login_required
    def get(self, request):
        if not request.GET.get("username") and not request.user.is_authenticated:
            return self.error("Please login first", "permission-denied")
        # Only SuperAdmin can query other users' contest detail
        if request.GET.get("username") and request.user.is_authenticated:
            if request.GET["username"] != request.user.username:
                if request.user.admin_type != AdminType.SUPER_ADMIN:
                    return self.error("Permission denied")
        contest_id = request.GET.get("contest_id")
        if not contest_id:
            return self.error("Parameter error")

        try:
            target_user = self._get_target_user(request)
        except User.DoesNotExist:
            return self.error("User does not exist")

        try:
            contest = Contest.objects.get(id=contest_id, visible=True)
        except Contest.DoesNotExist:
            return self.error("Contest does not exist")

        if (contest.rule_type == ContestRuleType.OI and contest.status == ContestStatus.CONTEST_UNDERWAY
                and not contest.real_time_rank and not request.user.is_contest_admin(contest)):
            return self.error("No permission to get ranks")

        participation = ContestParticipation.objects.filter(contest=contest, user=target_user).first()
        my_rank = None
        submission_count = participation.submission_number if participation else 0
        ac_count = participation.accepted_number if participation else 0
        total_score = participation.total_score if participation else 0
        submission_info = {}

        if contest.rule_type == ContestRuleType.ACM:
            rank = ACMContestRank.objects.filter(contest=contest, user=target_user).first()
            if rank:
                my_rank = self._acm_rank_position(contest, rank)
                submission_count = rank.submission_number
                ac_count = rank.accepted_number
                submission_info = rank.submission_info or {}
        else:
            rank = OIContestRank.objects.filter(contest=contest, user=target_user).first()
            if rank:
                my_rank = self._oi_rank_position(contest, rank)
                total_score = rank.total_score
                submission_count = rank.submission_number
                submission_info = rank.submission_info or {}

        if not participation and not submission_info:
            return self.error("No participation record in this contest")

        problems = list(Problem.objects.filter(contest_id=contest.id, visible=True)
                        .values("id", "_id", "title")
                        .order_by("_id"))

        from contest.scoring import eligible_submissions
        accepted_problems = set(eligible_submissions(contest).filter(user_id=target_user.pk, result=JudgeStatus.ACCEPTED)
                                .values_list("problem_id", flat=True))
        problem_items = []
        for problem in problems:
            info = submission_info.get(str(problem["id"]))
            if contest.rule_type == ContestRuleType.ACM:
                # info = {"is_ac": bool, "ac_time": int, "error_number": int, ...}
                is_ac = bool(info and info.get("is_ac"))
                error_number = info.get("error_number", 0) if info else 0
                ac_time = info.get("ac_time") if (info and is_ac) else None
                problem_items.append({
                    "display_id": problem["_id"],
                    "title": problem["title"],
                    "is_ac": is_ac,
                    "error_number": error_number,
                    "ac_time": ac_time,
                    "best_score": None
                })
            else:
                # info = score (int) or None
                best_score = info if info is not None else 0
                is_ac = problem["id"] in accepted_problems
                problem_items.append({
                    "display_id": problem["_id"],
                    "title": problem["title"],
                    "is_ac": is_ac,
                    "error_number": 0,
                    "ac_time": None,
                    "best_score": best_score
                })

        return self.success({
            "contest_id": contest.id,
            "contest_title": contest.title,
            "rule_type": contest.rule_type,
            "my_rank": my_rank,
            "submission_count": submission_count,
            "ac_count": ac_count,
            "total_score": total_score,
            "problem_items": problem_items
        })


class ContestCalibrateAPI(APIView):
    """
    Manually trigger calibration for a specific contest.
    This allows users to re-sync data from rank tables into participation record.
    """

    @login_required
    @check_contest_permission(check_type="ranks")
    def post(self, request):
        user = request.user

        try:
            # Force calibration regardless of previous state. If participation
            # does not exist yet, calibrate_once will create it automatically.
            participation = ContestParticipation.calibrate_once(user, self.contest, force=True)
            return self.success({
                "success": True,
                "is_calibrated": participation.is_calibrated,
                "submission_number": participation.submission_number,
                "accepted_number": participation.accepted_number,
                "total_score": participation.total_score
            })
        except Exception as e:
            logger.error("contest_calibration_error type=%s", type(e).__name__)
            return self.error("Calibration failed; please try again later")


class OpenAPIAppkeyAPI(APIView):
    @login_required
    def post(self, request):
        user = request.user
        if not user.open_api:
            return self.error("OpenAPI function is truned off for you")
        api_appkey = rand_str()
        user.open_api_appkey = api_appkey
        user.save()
        return self.success({"appkey": api_appkey})


class SSOAPI(CSRFExemptAPIView):
    @login_required
    def get(self, request):
        token = rand_str()
        request.user.auth_token = token
        request.user.save()
        return self.success({"token": token})

    @method_decorator(csrf_exempt)
    @validate_serializer(SSOSerializer)
    def post(self, request):
        try:
            user = User.objects.get(auth_token=request.data["token"])
        except User.DoesNotExist:
            return self.error("User does not exist")
        return self.success({"username": user.username, "avatar": user.userprofile.avatar, "admin_type": user.admin_type})

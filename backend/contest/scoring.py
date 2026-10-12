"""Rebuild contest projections from eligible, durable verdicts."""
from collections import Counter, defaultdict

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from account.models import AdminType, User, UserProfile
from problem.models import Problem
from submission.models import JudgeStatus, Submission
from utils.cache import cache
from utils.constants import CacheKey, ContestRuleType, ContestStatus
from .models import ACMContestRank, Contest, ContestParticipation, OIContestRank


SCORED_RESULTS = (JudgeStatus.COMPILE_ERROR, JudgeStatus.WRONG_ANSWER, JudgeStatus.ACCEPTED,
                  JudgeStatus.CPU_TIME_LIMIT_EXCEEDED, JudgeStatus.REAL_TIME_LIMIT_EXCEEDED,
                  JudgeStatus.MEMORY_LIMIT_EXCEEDED, JudgeStatus.RUNTIME_ERROR, JudgeStatus.PARTIALLY_ACCEPTED)


def eligible_submissions(contest):
    users = User.objects.filter(is_disabled=False, admin_type=AdminType.REGULAR_USER).exclude(pk=contest.created_by_id)
    return Submission.objects.filter(contest=contest, problem__contest=contest, problem__visible=True,
                                     problem__rule_type=contest.rule_type, user_id__in=users.values("pk"),
                                     create_time__gte=contest.start_time, create_time__lte=contest.end_time,
                                     result__in=SCORED_RESULTS)


def oi_score(row, problem):
    if row["result"] not in (JudgeStatus.ACCEPTED, JudgeStatus.PARTIALLY_ACCEPTED):
        return 0
    stats = row["statistic_info"]
    score = stats.get("score") if isinstance(stats, dict) else None
    return score if type(score) is int and 0 <= score <= max(problem.total_score, 0) else 0


def invalidate_rank_cache(contest):
    # Preserve the existing ACM frozen snapshot during the contest; ended contests always read live ranks.
    if contest.real_time_rank or contest.rule_type == ContestRuleType.OI or contest.status == ContestStatus.CONTEST_ENDED:
        transaction.on_commit(lambda: cache.delete(f"{CacheKey.contest_rank_cache}:{contest.pk}"))


@transaction.atomic
def rebuild_contest_scores(contest_id, user_id=None, problem_id=None):
    # A short contest lock serializes different submissions; no remote judging happens inside it.
    contest = Contest.objects.select_for_update().get(pk=contest_id)
    problems = {p.pk: p for p in Problem.objects.filter(contest=contest).order_by("pk")}
    eligible = eligible_submissions(contest)
    selected = eligible if user_id is None else eligible.filter(user_id=user_id)
    rows = list(selected.order_by("create_time", "pk").values("id", "user_id", "problem_id", "result", "create_time", "statistic_info"))
    by_user = defaultdict(list)
    for row in rows:
        by_user[row["user_id"]].append(row)
    rank_model = ACMContestRank if contest.rule_type == ContestRuleType.ACM else OIContestRank
    old_ranks = rank_model.objects.filter(contest=contest)
    if user_id is not None:
        old_ranks = old_ranks.filter(user_id=user_id)
    old_ranks = {rank.user_id: rank for rank in old_ranks}
    user_ids = {user_id} if user_id is not None else set(by_user) | set(old_ranks) | set(
        ContestParticipation.objects.filter(contest=contest).values_list("user_id", flat=True))
    affected_problems = set(problems) if user_id is None else {row["problem_id"] for row in rows}
    for rank in old_ranks.values():
        affected_problems.update(int(pk) for pk in rank.submission_info if pk.isdigit())
    if problem_id is not None:
        affected_problems.add(problem_id)
    first_ac = dict(eligible.filter(problem_id__in=affected_problems, result=JudgeStatus.ACCEPTED)
                    .order_by("problem_id", "create_time", "pk").distinct("problem_id").values_list("problem_id", "user_id"))

    # Lock users in one order, shared with ordinary-problem profile updates.
    for user in User.objects.select_for_update().filter(pk__in=user_ids).order_by("pk"):
        user_rows = by_user[user.pk]
        by_problem = defaultdict(list)
        for row in user_rows:
            by_problem[row["problem_id"]].append(row)
        old_rank = old_ranks.get(user.pk)
        previous = old_rank.submission_info if old_rank else {}
        info, statuses = {}, {}
        accepted, total_time, total_score = 0, 0, 0
        for pid, attempts in by_problem.items():
            key, problem = str(pid), problems[pid]
            if contest.rule_type == ContestRuleType.ACM:
                ac = next((row for row in attempts if row["result"] == JudgeStatus.ACCEPTED), None)
                before_ac = attempts[:attempts.index(ac)] if ac else attempts
                errors = sum(row["result"] != JudgeStatus.COMPILE_ERROR for row in before_ac)
                ac_time = int((ac["create_time"] - contest.start_time).total_seconds()) if ac else 0
                value = {"is_ac": bool(ac), "ac_time": ac_time, "error_number": errors,
                         "is_first_ac": bool(ac) and first_ac.get(pid) == user.pk}
                old = previous.get(key, {})
                if ac and old.get("is_ac") and old.get("ac_time") == ac_time and "checked" in old:
                    value["checked"] = old["checked"]
                info[key] = value
                if ac:
                    accepted += 1
                    total_time += ac_time + errors * 20 * 60
                statuses[key] = {"status": (ac or attempts[-1])["result"], "_id": problem._id}
            else:
                best = max(attempts, key=lambda row: (oi_score(row, problem), row["result"] == JudgeStatus.ACCEPTED))
                score = oi_score(best, problem)
                info[key] = score
                total_score += score
                has_ac = any(row["result"] == JudgeStatus.ACCEPTED for row in attempts)
                accepted += has_ac
                statuses[key] = {"status": JudgeStatus.ACCEPTED if has_ac else best["result"], "score": score, "_id": problem._id}
        if user_rows:
            defaults = {"submission_number": len(user_rows), "submission_info": info}
            if contest.rule_type == ContestRuleType.ACM:
                defaults.update(accepted_number=accepted, total_time=total_time)
            else:
                defaults["total_score"] = total_score
            rank_model.objects.update_or_create(contest=contest, user=user, defaults=defaults)
        elif old_rank:
            old_rank.delete()
        profile = UserProfile.objects.filter(user=user).first()
        if profile:
            field = "acm_problems_status" if contest.rule_type == ContestRuleType.ACM else "oi_problems_status"
            document = getattr(profile, field) or {}
            old_statuses = document.get("contest_problems", {})
            removed = {str(pk) for pk in problems} | set(previous)
            # Also discard deleted problems, whose old contest foreign key is no longer available.
            existing = {str(pk) for pk in Problem.objects.filter(pk__in=[key for key in old_statuses if key.isdigit()]).values_list("pk", flat=True)}
            document["contest_problems"] = {key: value for key, value in old_statuses.items() if key not in removed and key in existing}
            document["contest_problems"].update(statuses)
            setattr(profile, field, document)
            profile.save(update_fields=[field])
        score_fields = {
            "has_submission": bool(user_rows), "submission_number": len(user_rows), "accepted_number": accepted,
            "total_score": total_score, "is_calibrated": True, "calibrated_at": timezone.now()}
        participation, created = ContestParticipation.objects.get_or_create(user=user, contest=contest, defaults=score_fields)
        if not created:
            # Score changes are not visits; preserve auto_now last_enter_time and concurrent entry counts.
            ContestParticipation.objects.filter(pk=participation.pk).update(**score_fields)

    # Only the changed problem needs fresh aggregate counts on a normal judge completion.
    stats_ids = affected_problems if problem_id is None else {problem_id}
    counts = defaultdict(Counter)
    for row in eligible.filter(problem_id__in=stats_ids).order_by().values("problem_id", "result").annotate(count=Count("pk")):
        counts[row["problem_id"]][str(row["result"])] = row["count"]
    for pid in stats_ids & set(problems):
        values = counts[pid]
        Problem.objects.filter(pk=pid).update(
            statistic_info=dict(values), submission_number=sum(values.values()), accepted_number=values.get(str(JudgeStatus.ACCEPTED), 0))
    if contest.rule_type == ContestRuleType.ACM and affected_problems:
        changed = Q()
        for pid in affected_problems:
            changed |= Q(submission_info__contains={str(pid): {"is_first_ac": True}})
        changed |= Q(user_id__in=first_ac.values())
        for rank in ACMContestRank.objects.filter(changed, contest=contest):
            updated = False
            for pid in affected_problems:
                info = rank.submission_info.get(str(pid))
                if info is not None:
                    flag = bool(info.get("is_ac")) and first_ac.get(pid) == rank.user_id
                    if info.get("is_first_ac") != flag:
                        info["is_first_ac"], updated = flag, True
            if updated:
                rank.save(update_fields=["submission_info"])
    invalidate_rank_cache(contest)
    return len(rows)

import hashlib
import json
import logging
from contextlib import contextmanager
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.db import connection, transaction, IntegrityError
from django.db.models import Count, F

from account.models import User
from conf.models import JudgeServer
from contest.models import ContestRuleType, ACMContestRank, OIContestRank, ContestStatus, ContestParticipation
from options.options import SysOptions
from problem.models import Problem, ProblemRuleType
from problem.utils import parse_problem_template
from submission.models import JudgeStatus, Submission
from utils.cache import cache
from utils.constants import CacheKey

logger = logging.getLogger(__name__)


# 继续处理在队列中的问题
def process_pending_task():
    if cache.llen(CacheKey.waiting_queue):
        # 防止循环引入
        from judge.tasks import judge_task
        tmp_data = cache.rpop(CacheKey.waiting_queue)
        if tmp_data:
            data = json.loads(tmp_data.decode("utf-8"))
            judge_task.send(**data)


class ChooseJudgeServer:
    def __init__(self):
        self.server = None

    def __enter__(self) -> [JudgeServer, None]:
        with transaction.atomic():
            servers = JudgeServer.objects.select_for_update().filter(is_disabled=False).order_by("task_number")
            servers = [s for s in servers if s.status == "normal"]
            for server in servers:
                if server.task_number <= server.cpu_core * 2:
                    server.task_number = F("task_number") + 1
                    server.save(update_fields=["task_number"])
                    self.server = server
                    return server
        return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.server:
            JudgeServer.objects.filter(id=self.server.id).update(task_number=F("task_number") - 1)


class DispatcherBase(object):
    def __init__(self):
        self.token = hashlib.sha256(SysOptions.judge_server_token.encode("utf-8")).hexdigest()

    def _request(self, url, data=None):
        kwargs = {"headers": {"X-Judge-Server-Token": self.token}}
        if data:
            kwargs["json"] = data
        try:
            response = requests.post(url, timeout=(5, getattr(settings, "JUDGE_RESPONSE_TIMEOUT", 120)), **kwargs)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error("judge_request_failed type=%s", type(e).__name__)


class SPJCompiler(DispatcherBase):
    def __init__(self, spj_code, spj_version, spj_language):
        super().__init__()
        spj_compile_config = list(filter(lambda config: spj_language == config["name"], SysOptions.spj_languages))[0]["spj"][
            "compile"]
        self.data = {
            "src": spj_code,
            "spj_version": spj_version,
            "spj_compile_config": spj_compile_config
        }

    def compile_spj(self):
        with ChooseJudgeServer() as server:
            if not server:
                return "No available judge_server"
            result = self._request(urljoin(server.service_url, "compile_spj"), data=self.data)
            if not result:
                return "Failed to call judge server"
            if result["err"]:
                return result["data"]


@contextmanager
def submission_worker_lock(submission_id):
    # Do not hold a database transaction while waiting on a remote judge.
    key = int.from_bytes(hashlib.sha256(("judge-worker:" + submission_id).encode()).digest()[:8],
                         "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
        acquired = cursor.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [key])


class JudgeDispatcher(DispatcherBase):
    def __init__(self, submission_id, problem_id):
        super().__init__()
        self.submission = Submission.objects.get(id=submission_id)
        self.contest_id = self.submission.contest_id

        if self.contest_id:
            self.problem = Problem.objects.select_related("contest").get(id=problem_id, contest_id=self.contest_id)
            self.contest = self.problem.contest
        else:
            self.problem = Problem.objects.get(id=problem_id)

    def _compute_statistic_info(self, resp_data):
        # 用时和内存占用保存为多个测试点中最长的那个
        self.submission.statistic_info["time_cost"] = max([x["cpu_time"] for x in resp_data])
        self.submission.statistic_info["memory_cost"] = max([x["memory"] for x in resp_data])

        # sum up the score in OI mode
        if self.problem.rule_type == ProblemRuleType.OI:
            score = 0
            try:
                for i in range(len(resp_data)):
                    if resp_data[i]["result"] == JudgeStatus.ACCEPTED:
                        resp_data[i]["score"] = self.problem.test_case_score[i]["score"]
                        score += resp_data[i]["score"]
                    else:
                        resp_data[i]["score"] = 0
            except IndexError:
                logger.error(f"Index Error raised when summing up the score in problem {self.problem.id}")
                self.submission.statistic_info["score"] = 0
                return
            self.submission.statistic_info["score"] = score

    def judge(self):
        with submission_worker_lock(self.submission.id) as acquired:
            if not acquired:
                return
            self.submission.refresh_from_db()
            # Terminal delivery is a replay unless an administrator explicitly
            # requested another judge run. JUDGING permits retry after a crash.
            if self.submission.result not in (JudgeStatus.PENDING, JudgeStatus.JUDGING) and not self.submission.statistic_info.get("_rejudge_pending"):
                return
            self._judge()

    def _judge(self):
        language = self.submission.language
        sub_config = list(filter(lambda item: language == item["name"], SysOptions.languages))[0]
        spj_config = {}
        if self.problem.spj_code:
            for lang in SysOptions.spj_languages:
                if lang["name"] == self.problem.spj_language:
                    spj_config = lang["spj"]
                    break

        if language in self.problem.template:
            template = parse_problem_template(self.problem.template[language])
            code = f"{template['prepend']}\n{self.submission.code}\n{template['append']}"
        else:
            code = self.submission.code

        data = {
            "language_config": sub_config["config"],
            "src": code,
            "max_cpu_time": self.problem.time_limit,
            "max_memory": 1024 * 1024 * self.problem.memory_limit,
            "test_case_id": self.problem.test_case_id,
            "output": False,
            "spj_version": self.problem.spj_version,
            "spj_config": spj_config.get("config"),
            "spj_compile_config": spj_config.get("compile"),
            "spj_src": self.problem.spj_code,
            "io_mode": self.problem.io_mode
        }

        with ChooseJudgeServer() as server:
            if not server:
                data = {"submission_id": self.submission.id, "problem_id": self.problem.id}
                cache.lpush(CacheKey.waiting_queue, json.dumps(data))
                return
            self.submission.result = JudgeStatus.JUDGING
            self.submission.statistic_info = {}
            self.submission.info = {}
            self.submission.save(update_fields=["result", "statistic_info", "info"])
            resp = self._request(urljoin(server.service_url, "/judge"), data=data)

        if not isinstance(resp, dict) or "err" not in resp or "data" not in resp or (not resp["err"] and not resp["data"]):
            self.submission.result = JudgeStatus.SYSTEM_ERROR
            self.submission.statistic_info = {"score": 0}
            with transaction.atomic():
                self.submission.save()
                if not self.contest_id:
                    self.update_problem_status()
            process_pending_task()
            return

        if resp["err"]:
            self.submission.result = JudgeStatus.COMPILE_ERROR
            self.submission.statistic_info["err_info"] = resp["data"]
            # self.submission.statistic_info["err_info_cn"] = GoogleTranslate(resp["data"])
            self.submission.statistic_info["score"] = 0
        else:
            resp["data"].sort(key=lambda x: int(x["test_case"]))
            self.submission.info = resp
            self._compute_statistic_info(resp["data"])
            error_test_case = list(filter(lambda case: case["result"] != 0, resp["data"]))
            # ACM模式下,多个测试点全部正确则AC，否则取第一个错误的测试点的状态
            # OI模式下, 若多个测试点全部正确则AC， 若全部错误则取第一个错误测试点状态，否则为部分正确
            if not error_test_case:
                self.submission.result = JudgeStatus.ACCEPTED
            elif self.problem.rule_type == ProblemRuleType.ACM or len(error_test_case) == len(resp["data"]):
                self.submission.result = error_test_case[0]["result"]
            else:
                self.submission.result = JudgeStatus.PARTIALLY_ACCEPTED
        # Result, legacy statistics and the learning outbox share one commit.
        # Duplicate delivery cannot leave a finalized result with counters applied twice.
        with transaction.atomic():
            self.submission.save()
            if self.contest_id:
                if self.contest.status != ContestStatus.CONTEST_UNDERWAY or \
                        User.objects.get(id=self.submission.user_id).is_contest_admin(self.contest):
                    logger.info("Contest debug mode, id: %s, submission id: %s", self.contest_id, self.submission.id)
                    return
                self.update_contest_problem_status()
                self.update_contest_rank()
            else:
                self.update_problem_status()
        process_pending_task()

    def update_problem_status_rejudge(self):
        return self.update_problem_status()

    def update_problem_status(self):
        # Derive aggregates from durable terminal submissions. This handles AC ->
        # WA -> AC, compile-error rejudges and another accepted submission without
        # increment/decrement bookkeeping or JSON integer/string-key ambiguity.
        with transaction.atomic():
            problem = Problem.objects.select_for_update().get(contest_id=None, id=self.problem.id)
            completed = Submission.objects.filter(problem=problem, contest_id=None).exclude(
                result__in=(JudgeStatus.PENDING, JudgeStatus.JUDGING))
            counts = {str(row["result"]): row["count"]
                      for row in completed.order_by().values("result").annotate(count=Count("pk"))}
            problem.statistic_info = counts
            problem.submission_number = sum(counts.values())
            problem.accepted_number = counts.get(str(JudgeStatus.ACCEPTED), 0)
            problem.save(update_fields=["accepted_number", "submission_number", "statistic_info"])

            user = User.objects.select_for_update().get(id=self.submission.user_id)
            profile = user.userprofile
            rows = completed.filter(user_id=user.pk)
            selected = rows.filter(result=JudgeStatus.ACCEPTED).order_by("-create_time", "-id").first()
            selected = selected or rows.order_by("-create_time", "-id").first()
            field = "acm_problems_status" if problem.rule_type == ProblemRuleType.ACM else "oi_problems_status"
            document = getattr(profile, field) or {}
            statuses = document.get("problems", {})
            problem_id = str(problem.pk)
            if selected:
                value = {"status": selected.result, "_id": problem._id}
                if problem.rule_type == ProblemRuleType.OI:
                    value["score"] = (selected.statistic_info or {}).get("score", 0)
                statuses[problem_id] = value
            else:
                statuses.pop(problem_id, None)
            document["problems"] = statuses
            setattr(profile, field, document)
            acm = (profile.acm_problems_status or {}).get("problems", {})
            oi = (profile.oi_problems_status or {}).get("problems", {})
            profile.accepted_number = sum(value.get("status") == JudgeStatus.ACCEPTED
                                          for value in list(acm.values()) + list(oi.values()))
            profile.total_score = sum(value.get("score", 0) or 0 for value in oi.values())
            profile.submission_number = Submission.objects.filter(
                user_id=user.pk, contest_id=None, problem__contest_id=None).exclude(
                result__in=(JudgeStatus.PENDING, JudgeStatus.JUDGING)).count()
            profile.save(update_fields=[field, "accepted_number", "submission_number", "total_score"])

    def update_contest_problem_status(self):
        with transaction.atomic():
            user = User.objects.select_for_update().get(id=self.submission.user_id)
            user_profile = user.userprofile
            problem_id = str(self.problem.id)
            if self.contest.rule_type == ContestRuleType.ACM:
                contest_problems_status = user_profile.acm_problems_status.get("contest_problems", {})
                if problem_id not in contest_problems_status:
                    contest_problems_status[problem_id] = {"status": self.submission.result, "_id": self.problem._id}
                elif contest_problems_status[problem_id]["status"] != JudgeStatus.ACCEPTED:
                    contest_problems_status[problem_id]["status"] = self.submission.result
                else:
                    # 如果已AC， 直接跳过 不计入任何计数器
                    return
                user_profile.acm_problems_status["contest_problems"] = contest_problems_status
                user_profile.save(update_fields=["acm_problems_status"])

            elif self.contest.rule_type == ContestRuleType.OI:
                contest_problems_status = user_profile.oi_problems_status.get("contest_problems", {})
                score = self.submission.statistic_info["score"]
                if problem_id not in contest_problems_status:
                    contest_problems_status[problem_id] = {"status": self.submission.result,
                                                           "_id": self.problem._id,
                                                           "score": score}
                else:
                    contest_problems_status[problem_id]["score"] = score
                    contest_problems_status[problem_id]["status"] = self.submission.result
                user_profile.oi_problems_status["contest_problems"] = contest_problems_status
                user_profile.save(update_fields=["oi_problems_status"])

            problem = Problem.objects.select_for_update().get(contest_id=self.contest_id, id=self.problem.id)
            result = str(self.submission.result)
            problem_info = problem.statistic_info
            problem_info[result] = problem_info.get(result, 0) + 1
            problem.submission_number += 1
            if self.submission.result == JudgeStatus.ACCEPTED:
                problem.accepted_number += 1
            problem.save(update_fields=["submission_number", "accepted_number", "statistic_info"])

    def update_contest_rank(self):
        if self.contest.rule_type == ContestRuleType.OI or self.contest.real_time_rank:
            cache.delete(f"{CacheKey.contest_rank_cache}:{self.contest.id}")

        def get_rank(model):
            return model.objects.select_for_update().get(user_id=self.submission.user_id, contest=self.contest)

        if self.contest.rule_type == ContestRuleType.ACM:
            model = ACMContestRank
            func = self._update_acm_contest_rank
        else:
            model = OIContestRank
            func = self._update_oi_contest_rank

        try:
            rank = get_rank(model)
        except model.DoesNotExist:
            try:
                model.objects.create(user_id=self.submission.user_id, contest=self.contest)
                rank = get_rank(model)
            except IntegrityError:
                rank = get_rank(model)
        func(rank)
        if self.contest.rule_type == ContestRuleType.ACM:
            ContestParticipation.sync_from_rank(
                user_id=self.submission.user_id,
                contest=self.contest,
                submission_number=rank.submission_number,
                accepted_number=rank.accepted_number,
                total_score=0
            )
        else:
            ContestParticipation.sync_from_rank(
                user_id=self.submission.user_id,
                contest=self.contest,
                submission_number=rank.submission_number,
                accepted_number=0,
                total_score=rank.total_score
            )

    def _update_acm_contest_rank(self, rank):
        info = rank.submission_info.get(str(self.submission.problem_id))
        # 因前面更改过，这里需要重新获取
        problem = Problem.objects.select_for_update().get(contest_id=self.contest_id, id=self.problem.id)
        # 此题提交过
        if info:
            if info["is_ac"]:
                return

            rank.submission_number += 1
            if self.submission.result == JudgeStatus.ACCEPTED:
                rank.accepted_number += 1
                info["is_ac"] = True
                info["ac_time"] = (self.submission.create_time - self.contest.start_time).total_seconds()
                rank.total_time += info["ac_time"] + info["error_number"] * 20 * 60

                if problem.accepted_number == 1:
                    info["is_first_ac"] = True
            elif self.submission.result != JudgeStatus.COMPILE_ERROR:
                info["error_number"] += 1

        # 第一次提交
        else:
            rank.submission_number += 1
            info = {"is_ac": False, "ac_time": 0, "error_number": 0, "is_first_ac": False}
            if self.submission.result == JudgeStatus.ACCEPTED:
                rank.accepted_number += 1
                info["is_ac"] = True
                info["ac_time"] = (self.submission.create_time - self.contest.start_time).total_seconds()
                rank.total_time += info["ac_time"]

                if problem.accepted_number == 1:
                    info["is_first_ac"] = True

            elif self.submission.result != JudgeStatus.COMPILE_ERROR:
                info["error_number"] = 1
        rank.submission_info[str(self.submission.problem_id)] = info
        rank.save()

    def _update_oi_contest_rank(self, rank):
        problem_id = str(self.submission.problem_id)
        current_score = self.submission.statistic_info["score"]
        last_score = rank.submission_info.get(problem_id)
        if last_score:
            rank.total_score = rank.total_score - last_score + current_score
        else:
            rank.total_score = rank.total_score + current_score
        rank.submission_info[problem_id] = current_score
        rank.save()

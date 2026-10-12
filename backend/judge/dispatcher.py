import hashlib
import logging
from contextlib import contextmanager
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.db import connection, transaction, DatabaseError, OperationalError
from django.db.models import Count
from django.utils import timezone

from account.models import User
from conf.models import JudgeServer
from contest.scoring import rebuild_contest_scores
from options.options import SysOptions
from problem.models import Problem, ProblemRuleType
from problem.utils import parse_problem_template
from submission.models import JudgeStatus, Submission
from .models import JudgeDispatch
from .services import dispatch_pending, set_dispatch_status

logger = logging.getLogger(__name__)


def process_pending_task():
    return dispatch_pending(limit=1)


def occupied_judge_slots(server_id):
    # Two-int negative server keys are separate from the bigint submission-worker locks.
    with connection.cursor() as cursor:
        cursor.execute("""SELECT objid FROM pg_locks WHERE locktype = 'advisory' AND granted
                          AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
                          AND classid = %s::oid AND objsubid = 2""", [(-server_id) & 0xffffffff])
        return {row[0] for row in cursor.fetchall()}


def sync_judge_server_tasks(server_id=None):
    with transaction.atomic():
        servers = JudgeServer.objects.select_for_update().order_by("id")
        if server_id is not None:
            servers = servers.filter(pk=server_id)
        for server in servers:
            count = len(occupied_judge_slots(server.pk))
            if server.task_number != count:
                JudgeServer.objects.filter(pk=server.pk).update(task_number=count)


class ChooseJudgeServer:
    def __init__(self):
        self.server = None
        self.slot = None
        self.session = None

    def __enter__(self) -> [JudgeServer, None]:
        try:
            with transaction.atomic():
                servers = JudgeServer.objects.select_for_update().filter(is_disabled=False).order_by("id")
                for server in servers:
                    if server.status != "normal":
                        continue
                    occupied = occupied_judge_slots(server.pk)
                    if len(occupied) >= server.cpu_core * 2:
                        continue
                    for slot in range(1, server.cpu_core * 2 + 1):
                        if slot in occupied:
                            continue
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [-server.pk, slot])
                            acquired = cursor.fetchone()[0]
                        if acquired:
                            self.server, self.slot, self.session = server, slot, connection.connection
                            sync_judge_server_tasks(server.pk)
                            return server
        except Exception:
            self.__exit__(None, None, None)
            raise
        return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.server is None:
            return
        session_lost = self.session is not connection.connection or self.session.closed
        try:
            # A reconnected session never owns the old reservation; do not unlock a new worker's slot.
            if self.session is connection.connection and not self.session.closed:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [-self.server.pk, self.slot])
            sync_judge_server_tasks(self.server.pk)
        except DatabaseError as error:
            logger.warning("judge_slot_release_failed server=%s type=%s", self.server.pk, type(error).__name__)
            # Close the owning session so PostgreSQL releases its advisory locks.
            if self.session is connection.connection:
                connection.close()
            session_lost = True
        if session_lost and exc_type is None:
            raise OperationalError("Judge database session was lost")


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
        session = connection.connection
    try:
        yield acquired
    finally:
        if acquired and session is connection.connection and not session.closed:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [key])
            except DatabaseError:
                connection.close()


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
            worker_session = connection.connection
            self.submission.refresh_from_db()
            # Terminal delivery is a replay unless an administrator explicitly
            # requested another judge run. JUDGING permits retry after a crash.
            if self.submission.result not in (JudgeStatus.PENDING, JudgeStatus.JUDGING) and not self.submission.statistic_info.get("_rejudge_pending"):
                set_dispatch_status(self.submission.pk, "done")
                return
            JudgeDispatch.objects.get_or_create(submission=self.submission)
            set_dispatch_status(self.submission.pk, "running")
            try:
                self._judge()
            except Exception:
                # Explicit failures keep the existing bounded actor retry policy; only interrupted running jobs auto-recover.
                if worker_session is connection.connection and not worker_session.closed:
                    JudgeDispatch.objects.filter(submission=self.submission, status="running").update(status="failed", updated_time=timezone.now())
                raise

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
                set_dispatch_status(self.submission.pk, "queued")
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
                set_dispatch_status(self.submission.pk, "done")
                if self.contest_id:
                    rebuild_contest_scores(self.contest_id, self.submission.user_id, self.problem.pk)
                else:
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
            set_dispatch_status(self.submission.pk, "done")
            if self.contest_id:
                rebuild_contest_scores(self.contest_id, self.submission.user_id, self.problem.pk)
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

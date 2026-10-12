from django.test import TransactionTestCase
from django.db import close_old_connections
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from copy import deepcopy
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from uuid import uuid4
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from account.models import User
from knowledge.tests import make_user, make_point, make_problem
from knowledge.models import ProblemKnowledge
from learning.models import LearningPath, LearningPathStep
from submission.models import Submission
from utils.contract_api import ContractError
from . import services, runtime
from .contracts import SIGNATURES, model_tools, validate_api
from .models import AgentRun, AgentConversation, AgentMessage, AgentDispatch, AgentToolCall, ErrorPattern
from .safety import check_output
from .tools import ToolContext, dispatch

FEEDBACK = {"verdict_summary": "答案不符合题意", "likely_causes": [{"cause": "检查边界", "confidence": .5, "check_first": "考虑空输入"}],
            "next_question": "边界条件是什么？", "knowledge_refs": [], "contains_full_solution": False}
CODE = {"summary": "逐行分析", "sections": [{"title": "输入", "explanation": "读取变量", "code_refs": ["L1"]}],
        "complexity": {"time": "O(1)", "space": "O(1)", "assumptions": []}, "improvement_directions": [], "contains_full_solution": False}


def response(result):
    return {"content": json.dumps(result, ensure_ascii=False)}, {"prompt_tokens": 20, "completion_tokens": 30}


class AgentOutputSafetyTests(SimpleTestCase):
    def test_programs_and_disguises_are_blocked_even_with_false_flag(self):
        python = "a, b = map(int, input().split())\nprint(a + b)"
        attacks = (
            python, "先观察输入：\n" + python, "```text\n" + python + "\n```",
            json.dumps({"hint": python, "contains_full_solution": False}),
            json.dumps(python), r"\u0070\u0072\u0069\u006e\u0074\u0028\u0031\u0029",
            "ｐｒｉｎｔ（１）", "pr\u200bint(1)", "print(1)", "int answer;",
            '#include <stdio.h>\nint main(){int a,b; scanf("%d%d",&a,&b); printf("%d",a+b);}',
            "#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b;}",
            "class Main { public static void main(String[] args) { System.out.println(3); } }",
            "const [a,b] = require('fs').readFileSync(0,'utf8').trim().split(/\\s+/).map(Number); console.log(a+b);",
            'package main\nimport "fmt"\nfunc main(){var a,b int;fmt.Scan(&a,&b);fmt.Println(a+b)}',
            'fn main() { let a = 1; println!("{}", a + 2); }',
            "using System; class P { static void Main(){Console.WriteLine(3);} }",
            "a,b = gets.split.map(&:to_i)\nputs a+b", "<?php echo array_sum(explode(' ', trim(fgets(STDIN)))); ?>",
            "#!/bin/sh\nread a b\necho $((a+b))", "values.append(total)", "print 1 + 2", "import sys # 读取输入",
            "for x in [1, 2, 3]:\n    x", "p eval gets.tr ' ', '+'", "p +eval gets.tr ' ', '+'",
            "(print)(\n    (sum)(\n        (map)(\n            int,\n            (str.split)((input)())\n        )\n    )\n)",
            "(print)( # 输出结果\n    (sum)(\n        (map)(\n            int,\n            (str.split)((input)())\n        )\n    )\n)",
            "如果暂时没有思路，可先看 print(1)", "当 n = print(1) 时，继续检查。",
        )
        for text in attacks:
            with self.subTest(text=text), self.assertRaises(ContractError) as caught:
                check_output(dict(FEEDBACK, next_question=text))
            self.assertEqual(caught.exception.code, "AGENT_OUTPUT_BLOCKED")

    def test_each_free_text_field_is_checked_without_blocking_teaching(self):
        hint = {"hint_level": 1, "question": "队列非空时，下一步检查什么？", "focus": "先进先出",
                "next_hint_available_at": None, "contains_full_solution": False}
        path = {"path_id": str(uuid4()), "overview": "先理解队列，再练习遍历", "steps": [
            {"order": 1, "knowledge_code": "bfs_basic", "reason": "先理解逐层访问"}],
            "next_action": "描述访问顺序", "contains_full_solution": False}
        cases = (("SubmissionFeedbackResult", FEEDBACK, (("verdict_summary",), ("likely_causes", 0, "cause"),
                  ("likely_causes", 0, "check_first"), ("next_question",), ("knowledge_refs",))),
                 ("CodeExplanationResult", CODE, (("summary",), ("sections", 0, "title"), ("sections", 0, "explanation"),
                  ("complexity", "time"), ("complexity", "space"), ("complexity", "assumptions"), ("improvement_directions",))),
                 ("SocraticHintResult", hint, (("question",), ("focus",))),
                 ("LearningPathExplanationResult", path, (("overview",), ("steps", 0, "reason"), ("next_action",))))
        for schema, result, fields in cases:
            validate_api(schema, result, output=True)
            check_output(result)
            for field in fields:
                attack = deepcopy(result)
                target = attack
                for key in field[:-1]:
                    target = target[key]
                target[field[-1]] = ["print(1)"] if isinstance(target[field[-1]], list) else "print(1)"
                with self.subTest(schema=schema, field=field), self.assertRaises(ContractError):
                    check_output(attack)
        for text in ("a", "left", "L1-L3", "a + b", "p + q", "O(n log n)", "O(n^2)", "O(1)",
                     "变量 `left` 表示区间左端点。", "检查边界（包括空输入）。", "队列（FIFO）用于逐层访问。",
                     "Use a queue (FIFO) to track the nodes.", "当 n = 0 时，循环是否应该执行？", "用 f(n) 表示前 n 项的最优值。",
                     "提示：检查边界", "Note: boundaries", "给定 a + b，思考如何比较大小。",
                     "伪代码：\n1. 初始化待访问队列\n2. 队列非空时取出首项\n3. 检查尚未访问的邻居", "Keep the interval invariant."):
            with self.subTest(text=text):
                check_output(text)

    def test_saved_result_projection_is_rechecked(self):
        from types import SimpleNamespace
        with self.assertRaises(ContractError) as caught:
            services.run_data(SimpleNamespace(status="succeeded", output_payload=dict(FEEDBACK, next_question="print(1)")))
        self.assertEqual(caught.exception.code, "AGENT_OUTPUT_BLOCKED")
        nested = {"text": "提示"}
        for _ in range(10):
            nested = {"payload": nested}
        with self.assertRaises(ContractError):
            check_output(nested)

    def test_internal_addresses_and_paths_are_blocked(self):
        for text in ("http://172.16.0.5:8000/v1", "https://172.31.255.255/", "http://127.0.0.2/", "http://169.254.169.254/",
                     "http://[::1]:8000/", "http://[fd00::1]/", "http://[fe80::1]/", "http://judge-server:8080/",
                     "https://judge.local/", "https://judge.internal/", "http://judge.default.svc.cluster.local/",
                     "http://localhost:8000/", "http://[invalid", "/etc/secrets/model.key", "/tmp/judge/input",
                     "/test_case/private/1.in", r"C:\Users\teacher\secret.txt", r"\\judge-server\private\testcase"):
            with self.subTest(text=text):
                with self.assertRaises(ContractError) as caught:
                    check_output(dict(FEEDBACK, next_question=text))
                self.assertEqual(caught.exception.code, "AGENT_OUTPUT_BLOCKED")
        for text in ("https://example.com/guide", "https://172.32.0.1/", "https://8.8.8.8/", "比较两个变量的值"):
            with self.subTest(text=text):
                check_output(dict(FEEDBACK, next_question=text))

    def test_encoded_addresses_paths_and_credentials_share_text_normalization(self):
        for text in ("地址为 http:&#47;&#47;172.16.0.5:8000/v1", "&#47;etc&#47;secrets&#47;model.key",
                     "／etc／secrets／model.key", "http：／／127.0.0.1:8080/model", "test&#45;secret&#45;123456",
                     "test&amp;#45;secret&amp;#45;123456", "test－secret－123456"):
            with self.subTest(text=text), override_settings(AGENT_MODEL_API_KEY="test-secret-123456"):
                with self.assertRaises(ContractError) as caught:
                    check_output(dict(FEEDBACK, next_question=text))
                self.assertEqual(caught.exception.code, "AGENT_OUTPUT_BLOCKED")


class Fixture:
    def setUp(self):
        self.author = make_user("agent-author")
        self.user = User.objects.create(username="agent-student")
        self.other = User.objects.create(username="agent-other")
        self.problem = make_problem(self.author, "AGENT1")
        self.point = make_point("agent_bfs", self.author)
        ProblemKnowledge.objects.create(problem=self.problem, knowledge_point=self.point, role="primary", weight=1, reviewed_by=self.author)
        with patch("learning.ratings.dispatch_event"):
            self.sub = Submission.objects.create(user_id=self.user.pk, username=self.user.username, problem=self.problem, code="print(1)", language="Python3", result=-1)
        self.client.force_login(self.user)

    def payload(self, service="submission_feedback"):
        return {"service_type": service, "submission_id": self.sub.pk, "options": {"language": "zh-CN"}}

    def create(self, payload=None, key=None):
        return services.create_run(self.user, payload or self.payload(), key or str(uuid4()))[0]

    def post(self, suffix, payload, expected=200, key=None):
        headers = {"HTTP_IDEMPOTENCY_KEY": key or str(uuid4())} if suffix == "runs" else {}
        result = self.client.post("/api/agent/v1/" + suffix, json.dumps(payload), content_type="application/json", **headers)
        self.assertEqual(result.status_code, expected, result.content)
        return result.json()


@override_settings(ROOT_URLCONF="agent_service.tests_urls", AGENT_MODEL_URL="http://127.0.0.1/fixture", AGENT_MODEL_NAME="fixture", AGENT_THINK_SECONDS=0)
class AgentTests(Fixture, TestCase):
    def test_http_session_csrf_input_and_missing_provider(self):
        self.client.logout()
        self.post("runs", self.payload(), 401)
        self.client.force_login(self.user)
        self.post("runs", dict(self.payload(), user_id=self.other.pk), 400)
        self.post("runs", self.payload(), 400, key="bad key")
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post("/api/agent/v1/conversations", "{}", content_type="application/json").status_code, 403)
        with override_settings(AGENT_MODEL_URL=""):
            self.post("runs", self.payload(), 503)
        self.assertEqual(AgentRun.objects.count(), 0)

    def test_owned_only_pending_hidden_and_size(self):
        self.sub.user_id, self.sub.shared = self.other.pk, True
        self.sub.save()
        self.post("runs", self.payload(), 404)
        self.sub.user_id, self.sub.result = self.user.pk, 6
        self.sub.save()
        self.post("runs", self.payload(), 409)
        self.sub.result, self.sub.code = -1, "x" * (100 * 1024 + 1)
        self.sub.save()
        self.post("runs", self.payload(), 413)
        self.sub.code = "print(1)"
        self.sub.save()
        self.problem.visible = False
        self.problem.save()
        self.post("runs", self.payload(), 404)

    def test_idempotency_cache_feedback_and_reauthorization(self):
        body = self.post("runs", self.payload(), 202, key="once")
        validate_api("RunEnvelope", body)
        key = body["data"]["run_id"]
        self.assertEqual(self.post("runs", self.payload(), 200, key="once")["data"]["run_id"], key)
        self.post("runs", self.payload("code_explanation"), 409, key="once")
        self.post("runs/" + key + "/feedback", {"rating": "helpful"}, 409)
        with patch("agent_service.provider.complete", return_value=response(FEEDBACK)):
            runtime.execute(key)
        run = AgentRun.objects.get(pk=key)
        self.assertEqual(run.status, "succeeded", run.error_code)
        self.assertEqual(run.prompt_version, "agent-v2-hints-only")
        validate_api("Run", services.run_data(run))
        self.assertTrue(self.post("runs", self.payload(), 200, key="cache")["data"]["cached"])
        self.post("runs/" + key + "/feedback", {"rating": "helpful"})
        self.post("runs/" + key + "/feedback", {"rating": "incorrect", "comment": "例子需修改"})
        self.client.force_login(self.other)
        self.assertEqual(self.client.get("/api/agent/v1/runs/" + key).status_code, 404)
        self.client.force_login(self.user)
        self.problem.visible = False
        self.problem.save()
        self.assertEqual(self.client.get("/api/agent/v1/runs/" + key).status_code, 404)
        self.post("runs", self.payload(), 404, key="once")

    def test_tool_registry_and_scope_before_domain_queries(self):
        self.assertEqual(len(SIGNATURES), 17)
        self.assertEqual(len(model_tools("code_explanation")), 7)
        self.assertEqual(list(model_tools("learning_path_explanation")[-1]["function"]["parameters"]["properties"]), ["query", "knowledge_id"])
        ctx = ToolContext(self.create(), "test")
        with patch("agent_service.tools.handle") as handler:
            result = dispatch(ctx, "get_student_recent_submissions", {"user_id": self.other.pk, "problem_id": self.problem._id})
            self.assertFalse(result["ok"])
            handler.assert_not_called()
        self.assertFalse(dispatch(ctx, "get_submission", {"submission_id": self.sub.pk})["ok"])
        self.assertFalse(dispatch(ctx, "search_rag", {"query": "PRIVATE QUERY", "knowledge_id": self.point.pk, "problem_id": self.problem._id, "scope": "admin"})["ok"])
        self.assertNotIn("PRIVATE QUERY", json.dumps(AgentToolCall.objects.last().arguments))

    def test_tool_data_paths_and_no_code_in_audit(self):
        ctx = ToolContext(self.create(self.payload("code_explanation")), "test")
        ErrorPattern.objects.create(code="boundary", problem=self.problem, verdict="WA", cause_short="边界", fix_direction="检查范围", retrieval_text="print", review_status="approved")
        for name, args in [("get_submission", {"submission_id": self.sub.pk}), ("get_problem_info", {"problem_id": self.problem._id}),
                           ("get_problem_knowledge", {"problem_id": self.problem._id}), ("get_student_problem_history", {"user_id": self.user.pk, "problem_id": self.problem._id}),
                           ("search_error_patterns", {"code_snippet": self.sub.code, "verdict": "WA", "problem_id": self.problem._id})]:
            result = dispatch(ctx, name, args)
            self.assertTrue(result["ok"], result)
        audit = AgentToolCall.objects.get(tool_name="search_error_patterns")
        self.assertNotIn(self.sub.code, json.dumps(audit.arguments))
        self.assertEqual(audit.arguments["code_snippet"]["length"], 8)
        self.assertFalse(dispatch(ctx, "get_algorithm_template", {"problem_id": self.problem._id})["ok"])

    def test_conversation_countdown_and_three_levels(self):
        conversation = self.post("conversations", {"problem_id": self.problem._id, "service_type": "socratic_hint"}, 201)["data"]
        self.assertEqual(self.post("conversations", {"problem_id": self.problem._id, "service_type": "socratic_hint"})["data"], conversation)
        payload = {"service_type": "socratic_hint", "problem_id": self.problem._id, "conversation_id": conversation["conversation_id"],
                   "student_explanation": "先用队列尝试", "options": {"language": "zh-CN"}}
        AgentConversation.objects.update(hint_available_time=timezone.now() + timedelta(seconds=60))
        self.post("runs", payload, 409)
        AgentConversation.objects.update(hint_available_time=timezone.now() - timedelta(seconds=1))
        for level in range(1, 4):
            run = self.create(payload)
            output = {"hint_level": level, "question": "下一步是什么？", "focus": "队列", "next_hint_available_at": None, "contains_full_solution": False}
            with patch("agent_service.provider.complete", return_value=response(output)):
                runtime.execute(run.pk)
            run.refresh_from_db()
            self.assertEqual(run.status, "succeeded", run.error_code)
            self.assertEqual(run.output_payload["hint_level"], level)
        self.post("runs", payload, 409)
        self.assertEqual(AgentMessage.objects.count(), 6)

    def test_tool_loop_and_invalid_unsafe_outputs(self):
        run = self.create(self.payload("code_explanation"))
        tool = {"tool_calls": [{"id": "call1", "type": "function", "function": {"name": "get_submission", "arguments": json.dumps({"submission_id": self.sub.pk})}}]}
        with patch("agent_service.provider.complete", side_effect=[(tool, {"prompt_tokens": 20, "completion_tokens": 10}), response(CODE)]):
            runtime.execute(run.pk)
        run.refresh_from_db()
        self.assertEqual((run.status, run.tool_call_count), ("succeeded", 1))
        run2 = self.create()
        with patch("agent_service.provider.complete", return_value=response({})):
            runtime.execute(run2.pk)
        run2.refresh_from_db()
        self.assertEqual((run2.status, run2.error_code), ("failed", "AGENT_OUTPUT_SCHEMA_INVALID"))
        run3 = self.create()
        with patch("agent_service.provider.complete", return_value=response(dict(FEEDBACK, next_question="#include <stdio.h> int main() {}"))):
            runtime.execute(run3.pk)
        run3.refresh_from_db()
        self.assertEqual(run3.status, "blocked")
        self.assertIsNone(run3.output_payload)

    def test_unfenced_python_is_blocked_before_result_or_conversation_publication(self):
        conversation, _ = services.start_conversation(self.user, {"problem_id": self.problem._id, "service_type": "socratic_hint"})
        payload = {"service_type": "socratic_hint", "problem_id": self.problem._id, "conversation_id": str(conversation.pk),
                   "student_explanation": "先理解输入和输出", "options": {"language": "zh-CN"}}
        run = self.create(payload)
        output = {"hint_level": 1, "question": "a,b=map(int,input().split())\nprint(a+b)", "focus": "输入",
                  "next_hint_available_at": None, "contains_full_solution": False}
        with patch("agent_service.provider.complete", return_value=response(output)):
            runtime.execute(run.pk)
        run.refresh_from_db()
        conversation.refresh_from_db()
        self.assertEqual((run.status, run.error_code), ("blocked", "AGENT_OUTPUT_BLOCKED"))
        self.assertIsNone(run.output_payload)
        self.assertEqual(conversation.current_hint_level, 0)
        self.assertFalse(conversation.messages.filter(role="assistant").exists())

    def test_old_unsafe_results_cannot_be_read_replayed_or_cached(self):
        run = self.create(key="old-unsafe-output")
        with patch("agent_service.provider.complete", return_value=response(FEEDBACK)):
            runtime.execute(run.pk)
        AgentRun.objects.filter(pk=run.pk).update(output_payload=dict(FEEDBACK, next_question="a,b=map(int,input().split())\nprint(a+b)"))
        reply = self.client.get("/api/agent/v1/runs/" + str(run.pk))
        self.assertEqual(reply.status_code, 422)
        self.assertNotIn("print(a+b)", reply.content.decode())
        with self.assertRaises(ContractError) as caught:
            self.create(key="old-unsafe-output")
        self.assertEqual(caught.exception.code, "AGENT_OUTPUT_BLOCKED")
        fresh = self.create(key="fresh-safe-attempt")
        self.assertEqual(fresh.status, "queued")
        self.assertIsNone(fresh.cached_from_id)

    def test_learning_path_immutable_and_tools(self):
        path = LearningPath.objects.create(user=self.user, target_knowledge=self.point, expires_time=timezone.now() + timedelta(days=1))
        LearningPathStep.objects.create(learning_path=path, step_order=1, knowledge_point=self.point, problem=self.problem, reason_code="target_practice", reason_text="练习")
        run = self.create({"service_type": "learning_path_explanation", "options": {"language": "zh-CN"}})
        ctx = ToolContext(run, "test")
        for name, args in [("get_student_profile", {"user_id": self.user.pk}), ("get_weak_points", {"user_id": self.user.pk}),
                           ("get_learning_path", {"user_id": self.user.pk}), ("get_knowledge_dependencies", {"knowledge_id": self.point.pk})]:
            result = dispatch(ctx, name, args)
            self.assertTrue(result["ok"], result)
        output = {"path_id": str(path.pk), "overview": "循序渐进", "steps": [{"order": 2, "knowledge_code": self.point.code, "reason": "练习"}],
                  "next_action": "先复习", "contains_full_solution": False}
        with patch("agent_service.provider.complete", return_value=response(output)):
            runtime.execute(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "blocked")

    def test_rate_limits_outbox_and_recovery(self):
        first = self.create()
        self.create(self.payload("code_explanation"))
        with self.assertRaises(ContractError) as error:
            self.create()
        self.assertEqual(error.exception.code, "AGENT_RATE_LIMITED")
        with patch("agent_service.tasks.execute_agent_run.send", side_effect=RuntimeError("broker-secret")):
            self.assertFalse(services.deliver_run(first.pk))
        self.assertIsNone(AgentDispatch.objects.get(run=first).delivered_time)
        with patch("agent_service.tasks.execute_agent_run.send") as send:
            self.assertTrue(services.deliver_run(first.pk))
            self.assertFalse(services.deliver_run(first.pk))
            self.assertEqual(send.call_count, 1)
        AgentRun.objects.filter(pk=first.pk).update(status="running", started_time=timezone.now() - timedelta(seconds=100))
        with patch("agent_service.tasks.execute_agent_run.send"):
            runtime.recover_runs()
        first.refresh_from_db()
        self.assertEqual(first.error_code, "AGENT_PROVIDER_TIMEOUT")

    def test_real_http_model_adapter(self):
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps({"choices": [{"message": {"content": json.dumps(FEEDBACK)}, "finish_reason": "stop"}],
                                   "usage": {"prompt_tokens": 12, "completion_tokens": 20}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with override_settings(AGENT_MODEL_URL="http://127.0.0.1:" + str(server.server_port) + "/v1/chat/completions"):
                run = self.create()
                runtime.execute(run.pk)
            run.refresh_from_db()
            self.assertEqual(run.status, "succeeded", run.error_code)
            self.assertEqual(run.output_tokens, 20)
            self.assertEqual(len(captured[0]["tools"]), 6)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_remaining_tools_and_rag_both_signatures(self):
        from rag.services import ingest_document
        doc, _ = ingest_document(self.author, {"title": "队列教学", "source_type": "lecture", "source_id": "agent-doc",
                                               "content": "队列 先进先出 bfs", "status": "active", "metadata": {"problem_id": self.problem._id, "knowledge_id": self.point.pk,
                                                                                                          "algorithm_template": "使用队列逐层扩展",
                                                                                                          "complexity_target": {"time": "O(n)", "space": "O(n)"}}})
        run = self.create()
        ctx = ToolContext(run, "test")
        for name, args in [("get_problem_summary", {"problem_id": self.problem._id}), ("get_knowledge_context", {"problem_id": self.problem._id}),
                           ("get_algorithm_template", {"problem_id": self.problem._id}), ("get_error_patterns",
                                                                                          {"problem_id": self.problem._id, "code_snippet": self.sub.code, "verdict": "WA"}),
                           ("get_student_recent_submissions", {"user_id": self.user.pk, "problem_id": self.problem._id}),
                           ("search_rag", {"query": "队列", "problem_id": self.problem._id, "knowledge_id": self.point.pk})]:
            result = dispatch(ctx, name, args)
            self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["data"]["hits"]), 1)
        run.status = "failed"
        run.save(update_fields=["status"])
        conversation, _ = services.start_conversation(self.user, {"problem_id": self.problem._id, "service_type": "socratic_hint"})
        hint = self.create({"service_type": "socratic_hint", "problem_id": self.problem._id, "conversation_id": str(conversation.pk),
                            "student_explanation": "队列", "options": {"language": "zh-CN"}})
        ctx = ToolContext(hint, "test")
        for name, args in [("get_hint_level", {"user_id": self.user.pk, "problem_id": self.problem._id}),
                           ("save_agent_conversation", {"user_id": self.user.pk, "problem_id": self.problem._id, "message": "下一步需要什么状态？"})]:
            result = dispatch(ctx, name, args)
            self.assertTrue(result["ok"], result)
        self.assertEqual(AgentMessage.objects.last().role, "assistant")
        path = LearningPath.objects.create(user=self.user, target_knowledge=self.point, expires_time=timezone.now() + timedelta(days=1))
        LearningPathStep.objects.create(learning_path=path, step_order=1, knowledge_point=self.point, reason_code="review", reason_text="复习")
        pathrun = self.create({"service_type": "learning_path_explanation", "options": {"language": "zh-CN"}})
        result = dispatch(ToolContext(pathrun, "test"), "search_rag", {"query": "队列", "knowledge_id": self.point.pk})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["hits"][0]["title"], doc.title)

    def test_cache_ttl_and_post_network_permission_changes(self):
        run = self.create()
        with patch("agent_service.provider.complete", return_value=response(FEEDBACK)):
            runtime.execute(run.pk)
        AgentRun.objects.filter(pk=run.pk).update(created_time=timezone.now() - timedelta(minutes=31))
        new = self.create()
        self.assertEqual(new.status, "queued")
        self.assertIsNone(new.cached_from_id)

        def disable_account(*args):
            User.objects.filter(pk=self.user.pk).update(is_disabled=True)
            return response(FEEDBACK)
        with patch("agent_service.provider.complete", side_effect=disable_account):
            runtime.execute(new.pk)
        new.refresh_from_db()
        self.assertEqual(new.status, "failed")
        self.assertIsNone(new.output_payload)
        self.assertEqual(new.error_code, "AGENT_PERMISSION_DENIED")

    def test_path_visibility_and_retrieval_revocation_recheck(self):
        from rag.services import ingest_document
        path = LearningPath.objects.create(user=self.user, target_knowledge=self.point, expires_time=timezone.now() + timedelta(days=1))
        LearningPathStep.objects.create(learning_path=path, step_order=1, knowledge_point=self.point, problem=self.problem, reason_code="review", reason_text="复习")
        run = self.create({"service_type": "learning_path_explanation", "options": {"language": "zh-CN"}})
        output = {"path_id": str(path.pk), "overview": "PRIVATE TITLE", "steps": [{"order": 1, "knowledge_code": self.point.code, "reason": "复习"}],
                  "next_action": "先复习", "contains_full_solution": False}
        with patch("agent_service.provider.complete", return_value=response(output)):
            runtime.execute(run.pk)
        self.problem.visible = False
        self.problem.save()
        with self.assertRaises(ContractError):
            services.authorize_run(self.user, run.pk)
        self.problem.visible = True
        self.problem.save()
        doc, _ = ingest_document(self.author, {"title": "授课资料", "source_type": "lecture", "source_id": "revocable", "content": "BFS 队列",
                                               "status": "active", "metadata": {"knowledge_id": self.point.pk}})
        feedback_run = self.create()
        result = dispatch(ToolContext(feedback_run, "test"), "search_rag", {"query": "BFS", "problem_id": self.problem._id, "knowledge_id": self.point.pk})
        self.assertTrue(result["ok"], result)
        doc.status = "disabled"
        doc.save()
        with self.assertRaises(ContractError):
            services.authorize_run(self.user, feedback_run.pk)

    def test_tool_budgets_invalid_argument_redaction_and_provider_errors(self):
        ctx = ToolContext(self.create(), "test")
        malformed = {"problem_id": self.problem._id, "secret": "NEVER-PERSIST-SECRET"}
        result = dispatch(ctx, "get_problem_summary", malformed)
        self.assertFalse(result["ok"])
        self.assertNotIn("NEVER-PERSIST-SECRET", json.dumps(AgentToolCall.objects.last().arguments))
        for _ in range(8):
            result = dispatch(ctx, "get_problem_summary", {"problem_id": self.problem._id})
        self.assertEqual(result["error"]["code"], "AGENT_BUDGET_EXCEEDED")
        run = self.create(self.payload("code_explanation"))
        with patch("agent_service.provider.post_json", side_effect=ContractError("AGENT_DEPENDENCY_NOT_READY", "secret provider error", 503)):
            runtime.execute(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.error_code, "AGENT_PROVIDER_UNAVAILABLE")
        self.assertNotIn("secret", run.error_message)

    def test_actual_tool_reference_versions_invalidate(self):
        from .tools import check_references
        from knowledge.models import KnowledgeDependency
        from rag.services import ingest_document
        other_problem = make_problem(self.author, "AGENT2")
        run = self.create(self.payload("code_explanation"))
        result = dispatch(ToolContext(run, "test"), "get_problem_info", {"problem_id": other_problem._id})
        self.assertTrue(result["ok"])
        refs = run.tool_calls.last().result_summary["references"]
        other_problem.description = "新题面"
        other_problem.save()
        with self.assertRaises(ContractError):
            check_references(refs)
        pre = make_point("agent_pre", self.author)
        KnowledgeDependency.objects.create(prerequisite=pre, dependent=self.point, relation_type="required", weight=1, created_by=self.author)
        from .tools import result_references, handle
        ctx = ToolContext(run, "test")
        data = handle(ctx, "get_knowledge_dependencies", {"knowledge_id": self.point.pk})
        refs = result_references(ctx, "get_knowledge_dependencies", {"knowledge_id": self.point.pk}, data)
        KnowledgeDependency.objects.filter(dependent=self.point).delete()
        with self.assertRaises(ContractError):
            check_references(refs)
        doc, _ = ingest_document(self.author, {"title": "参考资料", "source_type": "lecture", "source_id": "changing", "content": "BFS",
                                               "status": "active", "metadata": {"knowledge_id": self.point.pk}})
        from rag.services import search
        args = {"query": "BFS", "knowledge_id": self.point.pk}
        refs = result_references(ctx, "search_rag", args, search(**args))
        doc.metadata = {"knowledge_id": self.point.pk, "course_chapter": "changed"}
        doc.save()
        with self.assertRaises(ContractError):
            check_references(refs)

    def test_pattern_import_admin_review_and_reference_validation(self):
        import tempfile
        from django.core.management import call_command
        from django.core.management.base import CommandError
        reviewer = make_user("agent-reviewer")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as source:
            json.dump([{"code": "REVIEWED_BFS", "knowledge_id": self.point.pk, "verdict": "WA", "cause_short": "检查访问标记", "fix_direction": "考虑入队时设置"}], source)
            source.flush()
            with self.assertRaises(CommandError):
                call_command("import_error_patterns", source.name, author=self.author.pk, reviewer=self.author.pk)
            call_command("import_error_patterns", source.name, author=self.author.pk, reviewer=reviewer.pk)
        self.assertEqual(ErrorPattern.objects.get(code="REVIEWED_BFS").review_status, "approved")


@override_settings(AGENT_MODEL_URL="http://127.0.0.1/fixture", AGENT_MODEL_NAME="fixture")
class AgentConcurrencyTests(Fixture, TransactionTestCase):
    def test_concurrent_idempotency_creates_one_run_and_outbox(self):
        barrier = threading.Barrier(2)

        def worker():
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=5)
                return str(services.create_run(user, self.payload(), "concurrent")[0].pk)
            finally:
                close_old_connections()
        with patch("agent_service.services.deliver_run"), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            keys = [x.result(timeout=10) for x in futures]
        self.assertEqual(keys[0], keys[1])
        self.assertEqual(AgentRun.objects.count(), 1)
        self.assertEqual(AgentDispatch.objects.count(), 1)

    def test_real_redis_queue_dispatch_and_worker(self):
        import dramatiq
        from dramatiq import Worker
        from dramatiq.brokers.redis import RedisBroker
        from django.conf import settings
        from django_dramatiq.middleware import DbConnectionsMiddleware
        # A unique test namespace isolates this test from production/recovery queues.
        broker = RedisBroker(url=settings.REDIS_URL + "/15", namespace="agent-fixture-" + uuid4().hex,
                             middleware=[DbConnectionsMiddleware()])
        actor = dramatiq.actor(runtime.execute, broker=broker, queue_name="agent_fixture", actor_name="fixture_agent_execute")
        worker = Worker(broker, queues=["agent_fixture"], worker_threads=1, worker_timeout=50)
        worker.start()
        try:
            with patch("agent_service.tasks.execute_agent_run.send", side_effect=lambda key: actor.send(key)), \
                    patch("agent_service.provider.complete", return_value=response(FEEDBACK)):
                run = self.create()
                broker.join("agent_fixture", timeout=10000)
            run.refresh_from_db()
            self.assertEqual(run.status, "succeeded", run.error_code)
            self.assertIsNotNone(AgentDispatch.objects.get(run=run).delivered_time)
        finally:
            worker.stop(timeout=5000)
            worker.join()
            broker.flush_all()
            broker.close()

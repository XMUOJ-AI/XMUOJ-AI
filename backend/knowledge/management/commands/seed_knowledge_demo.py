"""Local-only demo baseline for the knowledge acceptance checklist.

Safety rules: runs only with DEBUG on; demo accounts get random passwords printed once;
existing accounts or problems that do not match the demo definition are never modified;
all formal data goes through the normal submit + review services so audit events exist.
"""
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from account.models import AdminType, ProblemPermission, User, UserProfile
from problem.models import Problem, ProblemDifficulty, ProblemRuleType
from utils.contract_api import ContractError

from knowledge import services
from knowledge.models import (KnowledgeDependency, KnowledgeDependencyChangeRequest, KnowledgeMappingBatch,
                              KnowledgePoint, ProblemKnowledge)


ACCOUNTS = {
    "demo_student": (AdminType.REGULAR_USER, ProblemPermission.NONE),
    "demo_reviewer": (AdminType.SUPER_ADMIN, ProblemPermission.ALL),  # submits dependency/mapping requests
    "demo_approver": (AdminType.SUPER_ADMIN, ProblemPermission.ALL),  # reviews them (no self-review)
    "demo_admin_all": (AdminType.ADMIN, ProblemPermission.ALL),
    "demo_admin_own": (AdminType.ADMIN, ProblemPermission.OWN),
    "demo_admin_none": (AdminType.ADMIN, ProblemPermission.NONE),
}

POINTS = [
    ("demo_programming_basic", "编程基础", "basic", 1, "active", ["程序设计入门"], "变量、控制结构和函数等算法学习的共同基础。"),
    ("demo_complexity", "复杂度分析", "basic", 2, "active", ["时间复杂度", "空间复杂度"], "使用渐进复杂度衡量算法的时间和空间开销。"),
    ("demo_array", "数组", "data_structure", 2, "active", ["顺序表"], "连续存储、随机访问以及常见遍历操作。"),
    ("demo_stack", "栈", "data_structure", 2, "active", ["后进先出"], "遵循后进先出规则的线性数据结构。"),
    ("demo_queue", "队列", "data_structure", 2, "active", ["先进先出"], "遵循先进先出规则的线性数据结构。"),
    ("demo_tree", "树与二叉树", "data_structure", 3, "active", ["二叉树"], "树结构、遍历方式以及二叉树的基本性质。"),
    ("demo_graph", "图的基本概念", "graph", 3, "active", ["图论基础"], "顶点、边、邻接关系以及图的常见存储方式。"),
    ("demo_dfs", "深度优先搜索", "graph", 4, "active", ["DFS"], "沿分支深入并通过回溯遍历状态空间。"),
    ("demo_bfs", "广度优先搜索", "graph", 4, "active", ["BFS"], "借助队列按层次遍历图或状态空间。"),
    ("demo_shortest_path", "最短路径", "graph", 5, "active", ["Dijkstra"], "计算图中节点之间最小路径代价。"),
    ("demo_greedy", "贪心算法", "paradigm", 4, "active", ["贪心策略"], "每一步选择当前局部最优方案并构造整体解。"),
    ("demo_dynamic_programming", "动态规划", "paradigm", 5, "active", ["DP"], "利用状态、转移和重复子问题求解优化问题。"),
    ("demo_string_matching", "字符串匹配", "string", 4, "active", ["KMP"], "在文本中定位模式串并分析匹配效率。"),
    ("demo_number_theory", "基础数论", "mathematics", 3, "active", ["最大公约数"], "整除、素数、最大公约数和模运算基础。"),
    ("demo_union_find_draft", "并查集（草稿）", "data_structure", 4, "draft", ["DSU"], "用于维护不相交集合的草稿知识点。"),
    ("demo_legacy_search", "旧版搜索方法", "algorithm", 3, "deprecated", [], "用于验证管理端废弃状态，主站不会展示。"),
]

DEPENDENCIES = [
    ("demo_programming_basic", "demo_array", "required", "1.000"),
    ("demo_programming_basic", "demo_complexity", "recommended", "0.700"),
    ("demo_array", "demo_stack", "required", "0.900"),
    ("demo_array", "demo_queue", "required", "0.900"),
    ("demo_array", "demo_tree", "recommended", "0.600"),
    ("demo_stack", "demo_dfs", "recommended", "0.700"),
    ("demo_queue", "demo_bfs", "required", "1.000"),
    ("demo_graph", "demo_dfs", "required", "1.000"),
    ("demo_graph", "demo_bfs", "required", "1.000"),
    ("demo_bfs", "demo_shortest_path", "required", "0.900"),
    ("demo_complexity", "demo_greedy", "recommended", "0.600"),
    ("demo_complexity", "demo_dynamic_programming", "recommended", "0.700"),
]

# (display_id, owner, title, difficulty, description, samples)
PROBLEMS = [
    ("DEMO1000", "demo_admin_own", "演示：数组中的最大值", ProblemDifficulty.Low,
     "<p>给定一个整数数组，输出其中的最大值。</p>", [{"input": "5\n1 7 3 2 5", "output": "7"}]),
    ("DEMO1001", "demo_admin_own", "演示：图的广度优先遍历", ProblemDifficulty.Mid,
     "<p>从指定起点开始，输出无权图的广度优先遍历顺序。</p>", [{"input": "4 3\n1 2\n1 3\n2 4", "output": "1 2 3 4"}]),
    ("DEMO1002", "demo_reviewer", "演示：单源最短路径", ProblemDifficulty.High,
     "<p>计算非负权图中起点到其余节点的最短距离。</p>", [{"input": "3 3\n1 2 2\n2 3 3\n1 3 10", "output": "0 2 5"}]),
]

APPROVED_MAPPINGS = {
    "DEMO1000": [{"knowledge_code": "demo_array", "role": "primary", "weight": "1.000"},
                 {"knowledge_code": "demo_complexity", "role": "secondary", "weight": "0.400"}],
    "DEMO1001": [{"knowledge_code": "demo_bfs", "role": "primary", "weight": "1.000"},
                 {"knowledge_code": "demo_graph", "role": "prerequisite", "weight": "0.800"},
                 {"knowledge_code": "demo_queue", "role": "prerequisite", "weight": "0.700"}],
}
PENDING_MAPPING = ("DEMO1002", [{"knowledge_code": "demo_shortest_path", "role": "primary", "weight": "1.000"},
                                {"knowledge_code": "demo_graph", "role": "prerequisite", "weight": "0.800"},
                                {"knowledge_code": "demo_greedy", "role": "secondary", "weight": "0.500"}])
PENDING_DEPENDENCY = ("demo_dfs", "demo_dynamic_programming", "recommended", "0.500", "演示待审核依赖：搜索状态设计有助于理解动态规划。")
REJECTED_DEPENDENCY = ("demo_string_matching", "demo_number_theory", "recommended", "0.300", "演示待驳回依赖：用于审核历史筛选测试。")


class Command(BaseCommand):
    help = "Create the knowledge acceptance demo baseline (DEBUG only, idempotent, random demo passwords)."

    def add_arguments(self, parser):
        parser.add_argument("--reset-passwords", action="store_true",
                            help="Generate and print new passwords for the existing demo accounts.")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_knowledge_demo 只能在 DEBUG 开发环境运行，生产环境禁止写入演示数据。")
        try:
            with transaction.atomic():
                users, passwords = self.accounts(options["reset_passwords"])
                self.points(users["demo_reviewer"])
                for prerequisite, dependent, relation_type, weight in DEPENDENCIES:
                    if not KnowledgeDependency.objects.filter(prerequisite__code=prerequisite, dependent__code=dependent).exists():
                        change = self.submit_dependency(users, prerequisite, dependent, relation_type, weight, "演示正式依赖")
                        self.review(users, "dependency_change", change, approve=True)
                problems = self.problems(users)
                for display_id, mappings in APPROVED_MAPPINGS.items():
                    if not KnowledgeMappingBatch.objects.filter(problem=problems[display_id]).exists():
                        batch = self.submit_mapping(users, problems[display_id], mappings)
                        self.review(users, "problem_mapping", batch, approve=True)
                display_id, mappings = PENDING_MAPPING
                if not KnowledgeMappingBatch.objects.filter(problem=problems[display_id]).exists():
                    self.submit_mapping(users, problems[display_id], mappings)
                requests = ((PENDING_DEPENDENCY, None), (REJECTED_DEPENDENCY, False))
                for (prerequisite, dependent, relation_type, weight, reason), approve in requests:
                    if not KnowledgeDependencyChangeRequest.objects.filter(prerequisite__code=prerequisite,
                                                                           dependent__code=dependent).exists():
                        change = self.submit_dependency(users, prerequisite, dependent, relation_type, weight, reason)
                        if approve is not None:
                            self.review(users, "dependency_change", change, approve)
        except ContractError as exc:
            raise CommandError("写入演示数据失败（{}）：{}".format(exc.code, exc.message))
        self.report(passwords)

    def accounts(self, reset_passwords):
        users, passwords = {}, {}
        for username, (admin_type, permission) in ACCOUNTS.items():
            user = User.objects.filter(username__iexact=username).first()
            if user and (user.username, user.admin_type, user.problem_permission, user.is_disabled) != (
                    username, admin_type, permission, False):
                raise CommandError("已存在账号 {}，但角色或状态与演示定义不符；为避免误改真实账号，已停止。".format(user.username))
            if user is None:
                user = User(username=username, admin_type=admin_type, problem_permission=permission)
            if user.pk is None or reset_passwords:
                passwords[username] = secrets.token_urlsafe(12)
                user.set_password(passwords[username])
                user.save()
                UserProfile.objects.get_or_create(user=user)
            users[username] = user
        return users, passwords

    def points(self, author):
        for index, (code, name, category, level, status, aliases, description) in enumerate(POINTS, start=1):
            if KnowledgePoint.objects.filter(code=code).exists():
                continue
            point = services.create_point(author, {
                "code": code, "name": name, "description": description, "category": category, "level": level,
                "aliases": aliases, "metadata": {"course_chapter": "演示章节", "display_order": index}})
            for step in {"draft": (), "active": ("active",), "deprecated": ("active", "deprecated")}[status]:
                point = services.update_point(author, code, {"version": point.version, "status": step})

    def problems(self, users):
        problems = {}
        for display_id, owner, title, difficulty, description, samples in PROBLEMS:
            problem = Problem.objects.filter(_id=display_id, contest__isnull=True).first()
            if problem and problem.created_by_id != users[owner].pk:
                raise CommandError("题号 {} 已被非演示题目占用；为避免改动真实题目的知识点标注，已停止。".format(display_id))
            if problem is None:
                problem = Problem.objects.create(
                    _id=display_id, title=title, description=description, samples=samples, difficulty=difficulty,
                    input_description="<p>输入格式见题目描述。</p>", output_description="<p>输出计算结果。</p>",
                    hint="<p>知识点体系本地演示题，不包含真实判题数据。</p>", source="知识点体系演示数据",
                    test_case_id="knowledge_" + display_id.lower(), test_case_score=[], languages=["C++", "Python3"],
                    template={}, time_limit=1000, memory_limit=128, rule_type=ProblemRuleType.ACM, visible=True,
                    created_by=users[owner])
            problems[display_id] = problem
        return problems

    def submit_dependency(self, users, prerequisite, dependent, relation_type, weight, reason):
        data = {"operation": "create", "prerequisite_code": prerequisite, "dependent_code": dependent,
                "relation_type": relation_type, "weight": weight, "reason": reason}
        return services.submit_dependency(users["demo_reviewer"], data, self.request_id())

    def submit_mapping(self, users, problem, mappings):
        return services.submit_mapping(users["demo_reviewer"], problem.pk, {"base_version": 0, "mappings": mappings},
                                       self.request_id())

    def review(self, users, object_type, obj, approve):
        data = {"expected_updated_time": obj.updated_time, "reason": "演示数据：关系依据不足。"}
        services.review(users["demo_approver"], object_type, obj.pk, data, approve, self.request_id())

    def request_id(self):
        return "seed_knowledge_demo_" + secrets.token_hex(8)

    def report(self, passwords):
        demo = {"prerequisite__code__startswith": "demo_"}
        self.stdout.write(self.style.SUCCESS("知识点演示数据已就绪：active {} / draft {} / deprecated {} 个知识点，"
                                             "{} 条正式依赖，{} 道演示题，{} 道题有已批准标注，"
                                             "{} 条待审依赖申请，{} 个待审标注批次。".format(
                                                 *(KnowledgePoint.objects.filter(code__startswith="demo_", status=s).count()
                                                   for s in ("active", "draft", "deprecated")),
                                                 KnowledgeDependency.objects.filter(**demo).count(),
                                                 Problem.objects.filter(_id__startswith="DEMO", contest__isnull=True).count(),
                                                 ProblemKnowledge.objects.filter(problem___id__startswith="DEMO")
                                                 .values("problem").distinct().count(),
                                                 KnowledgeDependencyChangeRequest.objects.filter(status="pending", **demo).count(),
                                                 KnowledgeMappingBatch.objects.filter(status="pending",
                                                                                      problem___id__startswith="DEMO").count())))
        if not passwords:
            self.stdout.write("演示账号已存在，密码未改动；需要新密码请加 --reset-passwords。")
            return
        self.stdout.write(self.style.WARNING("以下随机密码只显示这一次，请自行保存（仅限本地测试）："))
        for username, password in passwords.items():
            self.stdout.write("  {:<16} {}".format(username, password))

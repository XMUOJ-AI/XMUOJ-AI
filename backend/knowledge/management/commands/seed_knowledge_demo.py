import uuid
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from account.models import AdminType, ProblemPermission, User, UserProfile
from problem.models import Problem, ProblemDifficulty, ProblemRuleType

from knowledge.models import (KnowledgeDependency,
                              KnowledgeDependencyChangeRequest,
                              KnowledgeMappingBatch, KnowledgePoint,
                              ProblemKnowledge)
from knowledge.services import (approved_version, create_dependency_request,
                                normalized, review_dependency,
                                review_mapping, submit_mapping)


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


PROBLEMS = [
    {
        "display_id": "DEMO1000",
        "title": "演示：数组中的最大值",
        "difficulty": ProblemDifficulty.Low,
        "description": "<p>给定一个整数数组，输出其中的最大值。</p>",
        "samples": [{"input": "5\n1 7 3 2 5", "output": "7"}],
    },
    {
        "display_id": "DEMO1001",
        "title": "演示：图的广度优先遍历",
        "difficulty": ProblemDifficulty.Mid,
        "description": "<p>从指定起点开始，输出无权图的广度优先遍历顺序。</p>",
        "samples": [{"input": "4 3\n1 2\n1 3\n2 4", "output": "1 2 3 4"}],
    },
    {
        "display_id": "DEMO1002",
        "title": "演示：单源最短路径",
        "difficulty": ProblemDifficulty.High,
        "description": "<p>计算非负权图中起点到其余节点的最短距离。</p>",
        "samples": [{"input": "3 3\n1 2 2\n2 3 3\n1 3 10", "output": "0 2 5"}],
    },
]


APPROVED_MAPPINGS = {
    "DEMO1000": [
        {"knowledge_code": "demo_array", "role": "primary", "weight": 1.0},
        {"knowledge_code": "demo_complexity", "role": "secondary", "weight": 0.4},
    ],
    "DEMO1001": [
        {"knowledge_code": "demo_bfs", "role": "primary", "weight": 1.0},
        {"knowledge_code": "demo_graph", "role": "prerequisite", "weight": 0.8},
        {"knowledge_code": "demo_queue", "role": "prerequisite", "weight": 0.7},
    ],
}


PENDING_MAPPING = [
    {"knowledge_code": "demo_shortest_path", "role": "primary", "weight": 1.0},
    {"knowledge_code": "demo_graph", "role": "prerequisite", "weight": 0.8},
    {"knowledge_code": "demo_greedy", "role": "secondary", "weight": 0.5},
]


class Command(BaseCommand):
    help = "Create an idempotent knowledge-system demo dataset for local testing."

    def _ensure_user(self, username, password, admin_type, problem_permission):
        user, _ = User.objects.get_or_create(username=username)
        user.admin_type = admin_type
        user.problem_permission = problem_permission
        user.is_disabled = False
        user.set_password(password)
        user.save()
        UserProfile.objects.get_or_create(user=user)
        return user

    def _ensure_problem(self, definition, owner):
        problem = Problem.objects.filter(_id=definition["display_id"], contest__isnull=True).first()
        values = {
            "title": definition["title"],
            "description": definition["description"],
            "input_description": "<p>输入格式见题目描述。</p>",
            "output_description": "<p>输出计算结果。</p>",
            "samples": definition["samples"],
            "test_case_id": "knowledge_{}".format(definition["display_id"].lower()),
            "test_case_score": [],
            "hint": "<p>这是知识点体系本地测试题，不包含真实判题数据。</p>",
            "languages": ["C++", "Python3"],
            "template": {},
            "created_by": owner,
            "time_limit": 1000,
            "memory_limit": 128,
            "rule_type": ProblemRuleType.ACM,
            "visible": True,
            "difficulty": definition["difficulty"],
            "source": "知识点体系演示数据",
        }
        if problem is None:
            problem = Problem.objects.create(_id=definition["display_id"], contest=None, **values)
        else:
            for field, value in values.items():
                setattr(problem, field, value)
            problem.save()
        return problem

    def _ensure_approved_mapping(self, problem, mappings, submitter, reviewer):
        if KnowledgeMappingBatch.objects.filter(problem=problem, approved_version__isnull=False).exists():
            return
        pending = KnowledgeMappingBatch.objects.filter(problem=problem, status="pending").first()
        if pending is None:
            pending = submit_mapping(problem, {"base_version": approved_version(problem), "mappings": mappings},
                                     submitter, "demo-seed-approved-{}".format(problem._id))
        review_mapping(pending, "approve", reviewer, "demo-seed-review-{}".format(problem._id))

    def handle(self, *args, **options):
        with transaction.atomic():
            owner = User.objects.filter(username="root", admin_type=AdminType.SUPER_ADMIN).first()
            if owner is None:
                owner = User.objects.filter(admin_type=AdminType.SUPER_ADMIN).order_by("id").first()
            if owner is None:
                raise CommandError("Create a Super Admin account before seeding demo data.")

            submitter = self._ensure_user("demo_reviewer", "DemoReview123!", AdminType.SUPER_ADMIN,
                                          ProblemPermission.ALL)
            self._ensure_user("demo_student", "DemoStudent123!", AdminType.REGULAR_USER,
                              ProblemPermission.NONE)

            points = {}
            for index, (code, name, category, level, status, aliases, description) in enumerate(POINTS, start=1):
                point, _ = KnowledgePoint.objects.update_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "normalized_name": normalized(name),
                        "description": description,
                        "category": category,
                        "level": level,
                        "status": status,
                        "aliases": aliases,
                        "metadata": {"course_chapter": "演示章节", "display_order": index},
                        "created_by": owner,
                    },
                )
                points[code] = point

            for prerequisite, dependent, relation_type, weight in DEPENDENCIES:
                KnowledgeDependency.objects.update_or_create(
                    prerequisite=points[prerequisite],
                    dependent=points[dependent],
                    defaults={
                        "relation_type": relation_type,
                        "weight": Decimal(weight),
                        "source": "manual",
                        "confidence": Decimal("1.000"),
                        "created_by": owner,
                    },
                )

            problems = {item["display_id"]: self._ensure_problem(item, owner) for item in PROBLEMS}
            for display_id, mappings in APPROVED_MAPPINGS.items():
                self._ensure_approved_mapping(problems[display_id], mappings, submitter, owner)

            pending_problem = problems["DEMO1002"]
            if not KnowledgeMappingBatch.objects.filter(problem=pending_problem, status="pending").exists():
                submit_mapping(pending_problem,
                               {"base_version": approved_version(pending_problem), "mappings": PENDING_MAPPING},
                               submitter, "demo-seed-pending-DEMO1002")

            pending_pair = (points["demo_dfs"], points["demo_dynamic_programming"])
            if not KnowledgeDependency.objects.filter(prerequisite=pending_pair[0], dependent=pending_pair[1]).exists() and not \
                    KnowledgeDependencyChangeRequest.objects.filter(prerequisite=pending_pair[0], dependent=pending_pair[1],
                                                                    operation="create", status="pending").exists():
                create_dependency_request({
                    "operation": "create",
                    "reason": "演示待审核依赖：搜索状态设计有助于理解动态规划。",
                    "prerequisite_code": pending_pair[0].code,
                    "dependent_code": pending_pair[1].code,
                    "relation_type": "recommended",
                    "weight": 0.5,
                }, submitter, "demo-seed-pending-dependency")

            rejected_pair = (points["demo_string_matching"], points["demo_number_theory"])
            if not KnowledgeDependencyChangeRequest.objects.filter(
                    prerequisite=rejected_pair[0], dependent=rejected_pair[1], operation="create",
                    status="rejected", reason__startswith="演示待驳回").exists():
                rejected = create_dependency_request({
                    "operation": "create",
                    "reason": "演示待驳回依赖：用于审核历史筛选测试。",
                    "prerequisite_code": rejected_pair[0].code,
                    "dependent_code": rejected_pair[1].code,
                    "relation_type": "recommended",
                    "weight": 0.3,
                }, submitter, "demo-seed-rejected-dependency")
                review_dependency(rejected, "reject", owner, "demo-seed-reject-review", "演示数据：关系依据不足。")

        self.stdout.write(self.style.SUCCESS(
            "Knowledge demo data ready: {} points, {} formal dependencies, {} demo problems, "
            "{} approved mappings, {} pending dependency requests, {} pending mapping batches.".format(
                KnowledgePoint.objects.filter(code__startswith="demo_").count(),
                KnowledgeDependency.objects.filter(prerequisite__code__startswith="demo_",
                                                   dependent__code__startswith="demo_").count(),
                Problem.objects.filter(_id__startswith="DEMO", contest__isnull=True).count(),
                ProblemKnowledge.objects.filter(problem___id__startswith="DEMO").count(),
                KnowledgeDependencyChangeRequest.objects.filter(status="pending",
                                                                prerequisite__code__startswith="demo_").count(),
                KnowledgeMappingBatch.objects.filter(status="pending", problem___id__startswith="DEMO").count(),
            )
        ))
        self.stdout.write("Demo accounts: demo_student / DemoStudent123!, demo_reviewer / DemoReview123!")

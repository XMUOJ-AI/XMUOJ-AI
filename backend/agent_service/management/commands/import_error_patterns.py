"""Operator import of reviewed pedagogical content; never exposed to an Agent tool."""
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from account.models import User
from knowledge.services import knowledge_write
from agent_service.models import ErrorPattern
from agent_service.tools import knowledge_point, visible_problem
from agent_service.safety import check_output
from utils.contract_api import ContractError


class Command(BaseCommand):
    help = "Import a JSON array of reviewed error patterns using two identified active administrators."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--author", type=int, required=True)
        parser.add_argument("--reviewer", type=int, required=True)

    def handle(self, file, author, reviewer, **options):
        try:
            author = User.objects.get(pk=author, is_disabled=False)
            reviewer = User.objects.get(pk=reviewer, is_disabled=False)
            if not author.is_super_admin() or not reviewer.is_super_admin() or author.pk == reviewer.pk:
                raise CommandError("作者与审核人须是两位不同的活动超级管理员")
            if Path(file).stat().st_size > 2 * 1024 * 1024:
                raise CommandError("文件超过2MiB")
            rows = json.loads(Path(file).read_text())
            if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
                raise CommandError("需要1至1000项JSON数组")
            with knowledge_write():
                for row in rows:
                    allowed = {"code", "problem_id", "knowledge_id", "verdict", "cause_short", "cause_detail", "fix_direction", "retrieval_text", "priority"}
                    if not isinstance(row, dict) or set(row) - allowed or any(not isinstance(row.get(x), str)
                                                                              or not row[x].strip() for x in ("code", "verdict", "cause_short", "fix_direction")):
                        raise CommandError("错误模式字段不合法")
                    if len(row["code"]) > 64 or row["verdict"] not in ("WA", "TLE", "MLE", "RE", "CE") or type(
                            row.get("priority", 100)) is not int or not -32768 <= row.get("priority", 100) <= 32767:
                        raise CommandError("错误模式代码、verdict或优先级不合法")
                    if any(not isinstance(row.get(x, ""), str) or len(row.get(x, "")) > 4000 for x in ("cause_short", "cause_detail", "fix_direction", "retrieval_text")):
                        raise CommandError("错误模式文本超过限制")
                    point = knowledge_point(row["knowledge_id"]) if row.get("knowledge_id") else None
                    problem = visible_problem(row["problem_id"]) if row.get("problem_id") else None
                    if not point and not problem:
                        raise CommandError("错误模式至少关联题目或知识点")
                    check_output({"cause_short": row["cause_short"], "fix_direction": row["fix_direction"]})
                    defaults = {key: row.get(key, "" if key != "priority" else 100) for key in ("cause_short", "cause_detail", "fix_direction", "retrieval_text", "priority")}
                    defaults.update(problem=problem, knowledge_point=point, verdict=row["verdict"], review_status="approved", created_by=author, reviewed_by=reviewer)
                    ErrorPattern.objects.update_or_create(code=row["code"], defaults=defaults)
            self.stdout.write(str(len(rows)) + " reviewed error patterns imported")
        except ContractError as exc:
            raise CommandError(exc.code + ": " + exc.message)
        except (User.DoesNotExist, ValueError, TypeError, OSError):
            raise CommandError("输入文件或管理员不存在/格式不合法")

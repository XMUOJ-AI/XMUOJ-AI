import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from account.models import User
from rag.services import ingest_document, index_document
from utils.contract_api import ContractError


class Command(BaseCommand):
    help = "Import reviewed RAG document JSON; never reads submissions or hidden tests."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--actor", type=int, required=True)
        parser.add_argument("--index", action="store_true")
        parser.add_argument("--create-collection", action="store_true")

    def handle(self, *args, **options):
        try:
            if options["create_collection"] and not options["index"]:
                raise CommandError("--create-collection 必须同时指定 --index")
            actor = User.objects.get(pk=options["actor"], is_disabled=False)
            path = Path(options["file"])
            if not path.is_file() or path.stat().st_size > 3 * 1024 * 1024:
                raise CommandError("导入文件须为不超过 3 MiB 的 JSON 文件")
            payload = json.loads(path.read_text(encoding="utf-8"))
            doc, created = ingest_document(actor, payload)
            count = index_document(doc.pk, options["create_collection"]) if options["index"] else 0
            self.stdout.write(json.dumps({"document_id": str(doc.pk), "created": created, "indexed_chunks": count}))
        except ContractError as exc:
            raise CommandError(exc.code + ": " + exc.message) from None
        except (User.DoesNotExist, ValueError, OSError):
            raise CommandError("输入文件或操作人不合法") from None

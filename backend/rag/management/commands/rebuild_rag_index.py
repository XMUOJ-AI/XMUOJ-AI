from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from rag.models import RagDocument
from rag.services import index_document
from utils.contract_api import ContractError


class Command(BaseCommand):
    help = "Rebuild real Milvus vectors, or remove a disabled document from the index."

    def add_arguments(self, parser):
        parser.add_argument("--document")
        parser.add_argument("--create-collection", action="store_true")

    def handle(self, *args, **options):
        docs = RagDocument.objects.order_by("id")
        create = options["create_collection"]
        count = 0
        try:
            if options["document"]:
                docs = docs.filter(pk=options["document"])
                if not docs.exists():
                    raise CommandError("资料不存在")
            for doc in docs.iterator():
                added = index_document(doc.pk, create and doc.status == "active")
                if added:
                    create = False
                count += added
        except ContractError as exc:
            raise CommandError(exc.code + ": " + exc.message) from None
        except ValidationError:
            raise CommandError("资料标识必须为 UUID") from None
        self.stdout.write("Indexed chunks: " + str(count))

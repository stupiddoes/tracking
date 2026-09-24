from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from api.models import MemoryAsset
from api.tasks import INDEX_ERRORS, index_memory_asset, mark_index_failed
from api.views import _index_memory_asset


class Command(BaseCommand):
    help = "Index memory photos that are missing, failed, or embedded with a different model."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Re-embed every photo.")
        parser.add_argument("--vision", action="store_true", help="Regenerate vision captions for every selected photo.")
        parser.add_argument("--queue", action="store_true", help="Send work to the Celery worker instead of running inline.")

    def handle(self, *args, **options):
        assets = MemoryAsset.objects.order_by("created_at")
        if not options["all"]:
            assets = assets.filter(
                ~Q(index_status=MemoryAsset.IndexStatus.READY)
                | Q(embedding__isnull=True)
                | ~Q(embedding_model=settings.EMBEDDING_MODEL)
            )
        total = assets.count()
        failed = 0
        for position, (asset_id, generated_caption) in enumerate(assets.values_list("id", "generated_caption"), 1):
            refresh_caption = options["vision"] or not generated_caption
            if options["queue"]:
                MemoryAsset.objects.filter(id=asset_id).update(index_status=MemoryAsset.IndexStatus.PENDING, index_error="")
                index_memory_asset.delay(str(asset_id), refresh_caption)
                continue
            try:
                _index_memory_asset(asset_id, refresh_caption)
            except INDEX_ERRORS as exc:
                failed += 1
                mark_index_failed(asset_id, exc)
                self.stderr.write(f"[{position}/{total}] {asset_id} failed: {exc}")
            else:
                self.stdout.write(f"[{position}/{total}] {asset_id} indexed")
        verb = "queued" if options["queue"] else "indexed"
        self.stdout.write(self.style.SUCCESS(f"{total - failed} photo(s) {verb}, {failed} failed."))

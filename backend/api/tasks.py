import httpx
from celery import shared_task

from .models import MemoryAsset

INDEX_ERRORS = (httpx.HTTPError, KeyError, IndexError, ValueError, OSError)


def mark_index_failed(asset_id, exc):
    MemoryAsset.objects.filter(id=asset_id).update(
        index_status=MemoryAsset.IndexStatus.FAILED,
        index_error=f"{type(exc).__name__}: {exc}"[:200],
    )


@shared_task(bind=True, max_retries=3)
def index_memory_asset(self, asset_id, refresh_caption=True):
    from .views import _index_memory_asset

    try:
        _index_memory_asset(asset_id, refresh_caption)
    except MemoryAsset.DoesNotExist:
        return
    except INDEX_ERRORS as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30 * 2 ** self.request.retries)
        mark_index_failed(asset_id, exc)

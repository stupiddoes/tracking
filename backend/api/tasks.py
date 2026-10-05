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


@shared_task
def export_book_task(book_id):
    from .books import export_book
    from .models import Book

    try:
        book = Book.objects.select_related("character").get(id=book_id)
    except Book.DoesNotExist:
        return
    try:
        export_book(book)
    except Exception as exc:  # Any failure must show as failed rather than leave the book "pending" forever.
        Book.objects.filter(id=book_id).update(
            export_status=Book.ExportStatus.FAILED, export_error=f"{type(exc).__name__}: {exc}"[:200],
        )

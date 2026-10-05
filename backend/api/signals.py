from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Book, MemoryAsset
from .thumbnails import delete_asset_files, thumbnail_prefix


@receiver(post_delete, sender=MemoryAsset)
def delete_memory_files(sender, instance, **kwargs):
    # Covers API, admin and cascades from deleting a character; files go only once the delete commits.
    storage, image_name, prefix = instance.image.storage, instance.image.name, thumbnail_prefix(instance)
    transaction.on_commit(lambda: delete_asset_files(storage, image_name, prefix))


@receiver(post_delete, sender=Book)
def delete_book_pdf(sender, instance, **kwargs):
    if instance.pdf.name:
        storage, name = instance.pdf.storage, instance.pdf.name
        transaction.on_commit(lambda: storage.delete(name))

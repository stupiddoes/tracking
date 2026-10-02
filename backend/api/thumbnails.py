"""JPEG thumbnails for memory photos, generated on first request and kept in media storage.

The URL carries a version derived from the original file name, so a replaced image gets
a new URL and clients (including an offline cache) never keep showing the old picture.
"""
import hashlib
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

THUMBNAIL_MAX_SIDE = 800


def jpeg_bytes(image_field, max_side, quality):
    """Upright, RGB JPEG of an image field scaled to fit within max_side."""
    image_field.open("rb")
    try:
        with Image.open(image_field) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((max_side, max_side))
            if image.mode != "RGB":
                image = image.convert("RGB")
            encoded = BytesIO()
            image.save(encoded, format="JPEG", quality=quality, optimize=True)
    finally:
        image_field.close()
    return encoded.getvalue()


def image_size(image_field):
    """(width, height) of the upright image, read from the file header only."""
    image_field.open("rb")
    try:
        with Image.open(image_field) as source:
            width, height = source.size
            orientation = source.getexif().get(0x0112)
    finally:
        image_field.close()
    # EXIF orientations 5–8 rotate the picture by 90 degrees.
    return (height, width) if orientation in (5, 6, 7, 8) else (width, height)


def thumbnail_version(asset):
    return hashlib.sha1(asset.image.name.encode()).hexdigest()[:10]


def thumbnail_prefix(asset):
    return f"thumbnails/{asset.owner_id}/{asset.id}-"


def thumbnail_name(asset):
    return f"{thumbnail_prefix(asset)}{thumbnail_version(asset)}.jpg"


def thumbnail_url(asset):
    return f"/api/v1/memory-assets/{asset.id}/thumbnail/?v={thumbnail_version(asset)}"


def ensure_thumbnail(asset):
    """Return the storage name of the asset's thumbnail, creating it if needed."""
    storage = asset.image.storage
    name = thumbnail_name(asset)
    if not storage.exists(name):
        storage.save(name, ContentFile(jpeg_bytes(asset.image, THUMBNAIL_MAX_SIDE, 78)))
    return name


def delete_asset_files(storage, image_name, prefix):
    """Delete the original image and every thumbnail version of one asset."""
    if image_name:
        storage.delete(image_name)
    directory, _, stem = prefix.rpartition("/")
    try:
        _, files = storage.listdir(directory)
    except FileNotFoundError:
        return
    for filename in files:
        if filename.startswith(stem):
            storage.delete(f"{directory}/{filename}")

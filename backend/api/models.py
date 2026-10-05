import uuid
from django.conf import settings
from django.db import models
from pgvector.django import VectorField

from .language import LANGUAGE_CHOICES, ZH


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    adult_confirmed_at = models.DateTimeField(null=True, blank=True)

    @property
    def adult_confirmed(self):
        return self.adult_confirmed_at is not None

class Character(models.Model):
    class Mode(models.TextChoices):
        MEMORIAL = "memorial", "回憶連結"
        FICTIONAL = "fictional", "幻想伙伴"
        ARCHIVE = "archive", "回憶整理"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="characters", null=True)
    name = models.CharField(max_length=80)
    mode = models.CharField(max_length=16, choices=Mode.choices)
    relationship = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    persona = models.JSONField(default=dict, blank=True)
    boundaries = models.JSONField(default=dict, blank=True)
    adult_content_enabled = models.BooleanField(default=False)
    # Language the AI uses for questions and photo descriptions in this album.
    language = models.CharField(max_length=8, choices=LANGUAGE_CHOICES, default=ZH)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name="conversations")
    summary = models.TextField(blank=True)
    summarized_message_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    embedding = VectorField(dimensions=768, null=True, blank=True)
    embedding_model = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


def memory_image_path(instance, filename):
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"memories/{instance.owner_id}/{instance.character_id}/{uuid.uuid4()}.{suffix}"


class MemoryAsset(models.Model):
    class Sensitivity(models.TextChoices):
        ORDINARY = "ordinary", "一般"
        ADULT = "adult", "成人"

    class DisplayPolicy(models.TextChoices):
        ON_REQUEST = "on_request", "只在要求時"
        RELATED = "related", "相關時可顯示"
        NEVER = "never", "不在對話顯示"

    class IndexStatus(models.TextChoices):
        PENDING = "pending", "索引中"
        READY = "ready", "已索引"
        FAILED = "failed", "索引失敗"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memory_assets")
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name="memory_assets")
    image = models.ImageField(upload_to=memory_image_path)
    # Pixel size of the original, for judging print quality in the photo book.
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    caption = models.TextField()
    generated_caption = models.TextField(blank=True)
    tags = models.CharField(max_length=500, blank=True)
    captured_at = models.DateField(null=True, blank=True)
    sensitivity = models.CharField(max_length=16, choices=Sensitivity.choices, default=Sensitivity.ORDINARY)
    display_policy = models.CharField(max_length=16, choices=DisplayPolicy.choices, default=DisplayPolicy.ON_REQUEST)
    embedding = VectorField(dimensions=768, null=True, blank=True)
    embedding_model = models.CharField(max_length=80, blank=True)
    index_status = models.CharField(max_length=16, choices=IndexStatus.choices, default=IndexStatus.PENDING)
    index_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


def book_pdf_path(instance, filename):
    return f"books/{instance.character.owner_id}/{instance.character_id}/{uuid.uuid4()}.pdf"


class Book(models.Model):
    """The printable A5 book for one album; photos are chosen from the album at export time."""

    class ExportStatus(models.TextChoices):
        NONE = "none", "未匯出"
        PENDING = "pending", "整理緊"
        READY = "ready", "完成"
        FAILED = "failed", "失敗"

    character = models.OneToOneField(Character, on_delete=models.CASCADE, related_name="book")
    title = models.CharField(max_length=120, blank=True)
    dedication = models.TextField(blank=True)
    # Ids of photos with a story that the user chose to leave out of the book.
    excluded = models.JSONField(default=list, blank=True)
    pdf = models.FileField(upload_to=book_pdf_path, blank=True)
    export_status = models.CharField(max_length=16, choices=ExportStatus.choices, default=ExportStatus.NONE)
    export_error = models.CharField(max_length=200, blank=True)
    exported_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

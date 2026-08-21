import uuid
from django.conf import settings
from django.db import models


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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="characters", null=True)
    name = models.CharField(max_length=80)
    mode = models.CharField(max_length=16, choices=Mode.choices)
    relationship = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    persona = models.JSONField(default=dict, blank=True)
    boundaries = models.JSONField(default=dict, blank=True)
    adult_content_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name="conversations")
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

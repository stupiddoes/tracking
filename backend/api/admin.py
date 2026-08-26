from django.contrib import admin
from .models import Character, Conversation, MemoryAsset, Message, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "adult_confirmed_at")
    search_fields = ("user__username",)
    readonly_fields = ("adult_confirmed_at",)


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "mode", "adult_content_enabled", "relationship", "created_at")
    list_filter = ("mode", "adult_content_enabled", "created_at")
    search_fields = ("name", "owner__username", "relationship")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "character", "created_at")
    search_fields = ("character__name", "character__owner__username")
    readonly_fields = ("summary", "summarized_message_count", "created_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "role", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("content", "conversation__character__name", "conversation__character__owner__username")
    readonly_fields = ("embedding", "embedding_model", "created_at")


@admin.register(MemoryAsset)
class MemoryAssetAdmin(admin.ModelAdmin):
    list_display = ("caption", "owner", "character", "sensitivity", "display_policy", "captured_at", "created_at")
    list_filter = ("sensitivity", "display_policy", "created_at")
    search_fields = ("caption", "generated_caption", "tags", "owner__username", "character__name")
    readonly_fields = ("generated_caption", "embedding", "embedding_model", "created_at")

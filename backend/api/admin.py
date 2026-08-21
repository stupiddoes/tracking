from django.contrib import admin
from .models import Character, Conversation, Message


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "mode", "relationship", "created_at")
    list_filter = ("mode", "created_at")
    search_fields = ("name", "owner__username", "relationship")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "character", "created_at")
    search_fields = ("character__name", "character__owner__username")
    readonly_fields = ("created_at",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "role", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("content", "conversation__character__name", "conversation__character__owner__username")
    readonly_fields = ("created_at",)

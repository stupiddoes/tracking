from django.contrib import admin
from .models import Character, Conversation, Message, Profile


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
    readonly_fields = ("created_at",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "role", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("content", "conversation__character__name", "conversation__character__owner__username")
    readonly_fields = ("created_at",)

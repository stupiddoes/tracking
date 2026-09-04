from django.contrib import admin
import mimetypes
from django.http import FileResponse, Http404
from django.urls import path, reverse
from django.utils.html import format_html
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
    list_display = ("thumbnail", "short_caption", "owner", "character", "sensitivity", "display_policy", "captured_at", "vision_status", "created_at")
    list_filter = ("sensitivity", "display_policy", "character__mode", "captured_at", "created_at")
    search_fields = ("caption", "generated_caption", "tags", "owner__username", "character__name")
    readonly_fields = ("image_preview", "image", "owner", "character", "generated_caption", "embedding", "embedding_model", "created_at")
    fields = (
        "image_preview", "image", "owner", "character", "caption", "generated_caption", "tags",
        "captured_at", "sensitivity", "display_policy", "embedding_model", "embedding", "created_at",
    )
    list_select_related = ("owner", "character")
    date_hierarchy = "created_at"
    list_per_page = 50
    actions = ("show_only_on_request", "allow_when_related", "hide_from_chat")

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        return [
            path(
                "<uuid:object_id>/preview/",
                self.admin_site.admin_view(self.preview),
                name="%s_%s_preview" % info,
            ),
        ] + super().get_urls()

    def preview(self, request, object_id):
        asset = self.get_object(request, object_id)
        if not asset or not self.has_view_permission(request, asset):
            raise Http404
        content_type = mimetypes.guess_type(asset.image.name)[0] or "application/octet-stream"
        return FileResponse(asset.image.open("rb"), content_type=content_type)

    def _preview_url(self, obj):
        info = self.model._meta.app_label, self.model._meta.model_name
        return reverse("admin:%s_%s_preview" % info, args=(obj.pk,))

    @admin.display(description="相片")
    def thumbnail(self, obj):
        return format_html(
            '<img src="{}" alt="" style="width:72px;height:72px;object-fit:cover;border-radius:8px" loading="lazy">',
            self._preview_url(obj),
        )

    @admin.display(description="原圖")
    def image_preview(self, obj):
        if not obj or not obj.pk:
            return "—"
        return format_html(
            '<img src="{}" alt="{}" style="max-width:640px;max-height:520px;object-fit:contain;border-radius:10px">',
            self._preview_url(obj), obj.caption,
        )

    @admin.display(description="描述", ordering="caption")
    def short_caption(self, obj):
        return obj.caption[:60] + ("…" if len(obj.caption) > 60 else "")

    @admin.display(description="Vision", boolean=True)
    def vision_status(self, obj):
        return bool(obj.generated_caption)

    @admin.action(description="設為：只在用戶要求時顯示")
    def show_only_on_request(self, request, queryset):
        queryset.update(display_policy=MemoryAsset.DisplayPolicy.ON_REQUEST)

    @admin.action(description="設為：對話相關時可以顯示")
    def allow_when_related(self, request, queryset):
        queryset.update(display_policy=MemoryAsset.DisplayPolicy.RELATED)

    @admin.action(description="設為：不在對話顯示")
    def hide_from_chat(self, request, queryset):
        queryset.update(display_policy=MemoryAsset.DisplayPolicy.NEVER)

    def delete_model(self, request, obj):
        storage, name = obj.image.storage, obj.image.name
        super().delete_model(request, obj)
        storage.delete(name)

    def delete_queryset(self, request, queryset):
        files = [(obj.image.storage, obj.image.name) for obj in queryset]
        super().delete_queryset(request, queryset)
        for storage, name in files:
            storage.delete(name)

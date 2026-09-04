from rest_framework import serializers
from .models import Character, Conversation, MemoryAsset, Message

class CharacterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Character
        fields = ("id", "name", "mode", "relationship", "description", "persona", "boundaries", "adult_content_enabled", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        enabled = attrs.get("adult_content_enabled", getattr(self.instance, "adult_content_enabled", False))
        mode = attrs.get("mode", getattr(self.instance, "mode", None))
        if enabled and mode != Character.Mode.FICTIONAL:
            raise serializers.ValidationError({"adult_content_enabled": "成人內容只適用於幻想伙伴。"})
        request = self.context.get("request")
        profile = getattr(request.user, "profile", None) if request and request.user.is_authenticated else None
        if enabled and not (profile and profile.adult_confirmed):
            raise serializers.ValidationError({"adult_content_enabled": "請先確認你已年滿 18 歲。"})
        return attrs

class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ("id", "role", "content", "metadata", "created_at")

class ConversationSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    class Meta:
        model = Conversation
        fields = ("id", "character", "created_at", "messages")


class MemoryAssetSerializer(serializers.ModelSerializer):
    content_url = serializers.SerializerMethodField()
    character = serializers.PrimaryKeyRelatedField(queryset=Character.objects.none())

    class Meta:
        model = MemoryAsset
        fields = (
            "id", "character", "image", "caption", "generated_caption", "tags", "captured_at",
            "sensitivity", "display_policy", "content_url", "created_at",
        )
        read_only_fields = ("id", "generated_caption", "content_url", "created_at")
        extra_kwargs = {
            "image": {"write_only": True},
            "caption": {"required": False, "allow_blank": True},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["character"].queryset = Character.objects.filter(owner=request.user)

    def validate_image(self, image):
        if image.size > 50 * 1024 * 1024:
            raise serializers.ValidationError("圖片不可超過 50 MB。")
        if getattr(image, "content_type", "") not in {
            "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
        }:
            raise serializers.ValidationError("只支援 JPEG、PNG、WebP、HEIC 或 HEIF。")
        return image

    def validate(self, attrs):
        if attrs.get("sensitivity") == MemoryAsset.Sensitivity.ADULT:
            character = attrs.get("character", getattr(self.instance, "character", None))
            profile = getattr(self.context["request"].user, "profile", None)
            if not (profile and profile.adult_confirmed and character.adult_content_enabled):
                raise serializers.ValidationError({"sensitivity": "成人圖片需要帳戶已確認 18+，而且伙伴已開啟成人內容。"})
        return attrs

    def get_content_url(self, obj):
        return f"/api/v1/memory-assets/{obj.id}/content/"

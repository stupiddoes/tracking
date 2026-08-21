from rest_framework import serializers
from .models import Character, Conversation, Message

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

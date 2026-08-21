from rest_framework import serializers
from .models import Character, Conversation, Message

class CharacterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Character
        fields = ("id", "name", "mode", "relationship", "description", "persona", "boundaries", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ("id", "role", "content", "metadata", "created_at")

class ConversationSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    class Meta:
        model = Conversation
        fields = ("id", "character", "created_at", "messages")

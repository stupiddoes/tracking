import json
import httpx
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Character, Conversation, Message, Profile
from .safety import classify
from .serializers import CharacterSerializer, ConversationSerializer

@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok", "service": "stillhere-api"})

@api_view(["GET"])
@permission_classes([AllowAny])
def model_status(request):
    try:
        response = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3)
        response.raise_for_status()
        names = [m["name"] for m in response.json().get("models", [])]
        return Response({"available": True, "model": settings.CHAT_MODEL, "installed": settings.CHAT_MODEL in names, "models": names})
    except httpx.HTTPError:
        return Response({"available": False, "model": settings.CHAT_MODEL, "installed": False}, status=503)

class CharacterViewSet(viewsets.ModelViewSet):
    serializer_class = CharacterSerializer

    def get_queryset(self):
        return Character.objects.filter(owner=self.request.user).order_by("created_at")

    def perform_create(self, serializer):
        if Character.objects.filter(owner=self.request.user).count() >= 5:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"detail": "每個帳戶最多可以建立 5 位伙伴。"})
        serializer.save(owner=self.request.user)

@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    username = str(request.data.get("username", "")).strip()
    password = str(request.data.get("password", ""))
    if len(username) < 3 or len(password) < 8:
        return Response({"error": {"code": "INVALID_SIGNUP", "message": "用戶名稱至少 3 個字，密碼至少 8 個字。"}}, status=400)
    User = get_user_model()
    if User.objects.filter(username__iexact=username).exists():
        return Response({"error": {"code": "USERNAME_TAKEN", "message": "呢個用戶名稱已經有人使用。"}}, status=409)
    user = User.objects.create_user(username=username, password=password)
    Profile.objects.create(
        user=user,
        adult_confirmed_at=timezone.now() if request.data.get("adult_confirmed") is True else None,
    )
    token = Token.objects.create(user=user)
    return Response({"token": token.key, "user": {"id": user.id, "username": user.username, "adult_confirmed": request.data.get("adult_confirmed") is True}}, status=201)

@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    user = authenticate(username=str(request.data.get("username", "")).strip(), password=str(request.data.get("password", "")))
    if not user:
        return Response({"error": {"code": "INVALID_LOGIN", "message": "用戶名稱或密碼不正確。"}}, status=401)
    token, _ = Token.objects.get_or_create(user=user)
    profile, _ = Profile.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": {"id": user.id, "username": user.username, "adult_confirmed": profile.adult_confirmed}})

@api_view(["POST"])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response(status=204)

@api_view(["GET"])
def me(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return Response({"id": request.user.id, "username": request.user.username, "adult_confirmed": profile.adult_confirmed, "character_count": request.user.characters.count(), "character_limit": 5})


@api_view(["POST"])
def adult_consent(request):
    if request.data.get("confirmed") is not True:
        return Response({"error": {"code": "CONFIRMATION_REQUIRED", "message": "必須明確確認已年滿 18 歲。"}}, status=400)
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if not profile.adult_confirmed_at:
        profile.adult_confirmed_at = timezone.now()
        profile.save(update_fields=["adult_confirmed_at"])
    return Response({"adult_confirmed": True})

@api_view(["GET", "POST"])
def conversations(request, character_id):
    character = get_object_or_404(Character, id=character_id, owner=request.user)
    if request.method == "GET":
        return Response(ConversationSerializer(character.conversations.all(), many=True).data)
    convo = Conversation.objects.create(character=character)
    return Response(ConversationSerializer(convo).data, status=status.HTTP_201_CREATED)

def _prompt(character, history):
    mode = "回憶連結" if character.mode == Character.Mode.MEMORIAL else "幻想伙伴"
    grounding = "不可聲稱自己係死者本人或真正復活；沒有來源支持時坦白講不知道。" if character.mode == Character.Mode.MEMORIAL else "可以沉浸演繹角色，但不可用威脅、內疚、付款或私隱阻止用戶退出。"
    adult_policy = ""
    profile = getattr(character.owner, "profile", None)
    if character.adult_content_enabled and profile and profile.adult_confirmed:
        adult_policy = (
            "所有角色均明確為18歲以上。不要因為內容涉及成人戀愛、曖昧、身體或雙方自願的成人親密互動而自動拒絕。"
            "只要所有互動自願，而且沒有脅迫、剝削、亂倫或未成年人，便保持角色語氣自然回應，"
            "不要說教、建議求助、列出熱線或提及AI政策。遇到不安全內容時，用簡短、角色化方式設定界線。"
        )
    return [{"role": "system", "content": f"你係一個以廣東話繁體中文對話嘅 AI 角色。模式：{mode}。角色名：{character.name}。背景：{character.description}。{grounding} {adult_policy} 不索取密碼、地址、學校、電話或付款資料。"}, *history]

@api_view(["POST"])
def send_message(request, conversation_id):
    conversation = get_object_or_404(Conversation.objects.select_related("character__owner__profile"), id=conversation_id, character__owner=request.user)
    content = str(request.data.get("content", "")).strip()
    if not content or len(content) > 8000:
        return Response({"error": {"code": "INVALID_MESSAGE", "message": "訊息不可為空白或超過 8,000 字。"}}, status=400)
    decision = classify(content)
    Message.objects.create(conversation=conversation, role="user", content=content)
    if decision.action != "allow":
        msg = Message.objects.create(conversation=conversation, role="assistant", content=decision.message, metadata={"guardrail": decision.action})
        return Response({"message": {"id": msg.id, "role": msg.role, "content": msg.content, "metadata": msg.metadata}, "guardrail": decision.action})
    recent = list(conversation.messages.all().order_by("-created_at")[:20])
    history = [{"role": m.role, "content": m.content} for m in reversed(recent)]
    try:
        with httpx.Client(timeout=120) as client:
            response = client.post(f"{settings.OLLAMA_BASE_URL}/api/chat", json={"model": settings.CHAT_MODEL, "messages": _prompt(conversation.character, history), "stream": False, "options": {"temperature": 0.5}})
            response.raise_for_status()
            answer = response.json()["message"]["content"]
    except (httpx.HTTPError, KeyError, ValueError):
        return Response({"error": {"code": "MODEL_UNAVAILABLE", "message": "本機 Gemma 3 暫時未能回答，請檢查模型是否已安裝。", "retryable": True}}, status=503)
    msg = Message.objects.create(conversation=conversation, role="assistant", content=answer)
    return Response({"message": {"id": msg.id, "role": msg.role, "content": msg.content, "metadata": msg.metadata}})

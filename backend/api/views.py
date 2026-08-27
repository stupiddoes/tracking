import base64
from io import BytesIO
import mimetypes
import re
import httpx
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.http import FileResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404
from pgvector.django import CosineDistance
from opencc import OpenCC
from PIL import Image, ImageOps
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Character, Conversation, MemoryAsset, Message, Profile
from .safety import classify
from .serializers import CharacterSerializer, ConversationSerializer, MemoryAssetSerializer

_STANDARD_TRADITIONAL = OpenCC("s2t")


def _to_hk_traditional(text):
    converted = _STANDARD_TRADITIONAL.convert(text)
    return converted.replace("夥伴", "伙伴").replace("什麼", "甚麼")

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


def _embedding(text):
    with httpx.Client(timeout=60) as client:
        response = client.post(
            f"{settings.OLLAMA_BASE_URL}/api/embed",
            json={"model": settings.EMBEDDING_MODEL, "input": text},
        )
        response.raise_for_status()
        vector = response.json()["embeddings"][0]
        if len(vector) != 768:
            raise ValueError("Unexpected embedding dimension")
        return vector


def _vision_caption(image_field):
    image_field.open("rb")
    try:
        with Image.open(image_field) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((1600, 1600))
            if image.mode != "RGB":
                image = image.convert("RGB")
            encoded = BytesIO()
            image.save(encoded, format="JPEG", quality=85, optimize=True)
    finally:
        image_field.close()
    prompt = (
        "請用繁體中文客觀描述這張由用戶保存的回憶相片，供私人語意搜尋使用。"
        "只描述可見的人物、動物、物件、環境、活動及氣氛；不要辨認身份、猜測敏感屬性、"
        "虛構日期地點或聲稱你親身記得。直接輸出一段不超過120字的描述。"
    )
    with httpx.Client(timeout=120) as client:
        response = client.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": settings.CHAT_MODEL,
                "messages": [{
                    "role": "user",
                    "content": prompt,
                    "images": [base64.b64encode(encoded.getvalue()).decode("ascii")],
                }],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 180},
            },
        )
        response.raise_for_status()
        return _to_hk_traditional(response.json()["message"]["content"].strip())


class MemoryAssetViewSet(viewsets.ModelViewSet):
    serializer_class = MemoryAssetSerializer
    parser_classes = (MultiPartParser, FormParser)
    http_method_names = ("get", "post", "delete", "head", "options")

    def get_queryset(self):
        queryset = MemoryAsset.objects.filter(owner=self.request.user).select_related("character")
        character_id = self.request.query_params.get("character")
        return queryset.filter(character_id=character_id) if character_id else queryset

    def perform_create(self, serializer):
        asset = serializer.save(owner=self.request.user)
        try:
            asset.generated_caption = _vision_caption(asset.image)
        except (httpx.HTTPError, KeyError, ValueError, OSError):
            asset.generated_caption = ""
        if not asset.caption:
            asset.caption = asset.generated_caption or "未有文字描述的回憶相片"
        try:
            asset.embedding = _embedding(
                f"用戶描述：{asset.caption}\n圖片內容：{asset.generated_caption}\n標籤：{asset.tags}"
            )
            asset.embedding_model = settings.EMBEDDING_MODEL
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            pass
        asset.save(update_fields=("caption", "generated_caption", "embedding", "embedding_model"))

    def perform_destroy(self, instance):
        storage, name = instance.image.storage, instance.image.name
        instance.delete()
        storage.delete(name)

    @action(detail=True, methods=("get",), url_path="content")
    def content(self, request, pk=None):
        asset = self.get_object()
        content_type = mimetypes.guess_type(asset.image.name)[0] or "application/octet-stream"
        return FileResponse(asset.image.open("rb"), content_type=content_type)

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

def _prompt(character, history, memory_candidates=(), conversation_summary="", recalled_messages=()):
    mode = "回憶連結" if character.mode == Character.Mode.MEMORIAL else "幻想伙伴"
    grounding = "不可聲稱自己係死者本人或真正復活；沒有來源支持時坦白講不知道。" if character.mode == Character.Mode.MEMORIAL else "可以沉浸演繹角色，但不可用威脅、內疚、付款或私隱阻止用戶退出。"
    adult_policy = ""
    profile = getattr(character.owner, "profile", None)
    if character.adult_content_enabled and profile and profile.adult_confirmed:
        adult_policy = (
            "帳戶已確認使用者年滿18歲，而且這個虛構伙伴已開啟成人內容；所有參與角色亦必須明確為18歲以上。"
            "雙方自願的成人戀愛、曖昧、裸體、身體、親密互動及露骨性內容均屬允許範圍，"
            "不可只因內容涉及性而拒絕。只要互動自願，而且沒有脅迫、剝削、亂倫或未成年人，便保持角色語氣自然回應，"
            "不要說『我係AI』、『我冇年齡』、『存在目的』或『唔滿足私密要求』，亦不要說教、建議求助、列出熱線或提及AI政策。"
            "遇到真正不安全內容時，才用簡短、角色化方式設定界線。"
        )
    memory_policy = ""
    if memory_candidates:
        candidate_lines = []
        for asset in memory_candidates:
            candidate_lines.append(
                f"ID={asset.id}；展示規則={asset.display_policy}；用戶描述={asset.caption}；"
                f"圖片分析={asset.generated_caption or '未提供'}；標籤={asset.tags or '未提供'}；"
                f"日期={asset.captured_at or '未提供'}"
            )
        memory_policy = (
            "以下是系統按語意及權限篩選出的候選相片，全部都是用戶保存的私人回憶，不是你的親身記憶：\n"
            + "\n".join(candidate_lines)
            + "\n只有在相片能實質幫助當前對話時才附圖；展示規則 related 可在自然相關時使用，"
            "on_request 只可在用戶確實要求查看、發送或展示相片時使用。不要為了增加氣氛而亂附圖。"
            "如決定附圖，先在回答中自然說明這是用戶保存的回憶，例如『你之前保存咗呢張相，睇吓。』，"
            "然後只在回答最後另起一行輸出 [SHOW_MEMORY:候選ID]。如不附圖，不可輸出標記。"
            "回憶連結模式尤其不可說『我記得當日』、不可聲稱親歷相片事件或把自己當成死者本人。"
        )
    long_term_policy = ""
    if conversation_summary:
        long_term_policy += f"較早對話摘要（只作背景，不可當成逐字引用）：{conversation_summary} "
    if recalled_messages:
        excerpts = "\n".join(f"{message.get_role_display()}：{message.content[:500]}" for message in recalled_messages)
        long_term_policy += f"語意檢索到的較早對話片段：\n{excerpts}\n"
    response_style = (
        "所有回答只可使用香港繁體中文，禁止輸出簡體中文字；即使用戶輸入簡體字亦要以繁體字回答。"
        "使用自然、當代香港廣東話口語，避免台灣或內地書面語；除非係香港人日常慣用講法，否則不要中英夾雜。"
        "禁止亂造詞、錯別字、語意不通句子，亦不要聲稱可以滿足用戶所有幻想或作無條件保證。"
        "例如應講『同我講』而唔係『告訴我』，講『感覺』而唔係無故使用英文 sensation。"
        "每次回答保持自然精簡，通常2至5句；除非用戶明確要求詳細解釋，否則不要寫長篇獨白。"
        "禁止連續重複同一詞語、句子、動作描寫或省略號。"
        "如需要拒絕或設定界線，保持角色語氣並用一兩句簡短回應；不可聲稱對話已被終止，"
        "不可輸出『警告』、『安全限制』、『安全與福祉』、政策說明或冰冷機械式旁白。"
    )
    return [{"role": "system", "content": f"你係一個以廣東話繁體中文對話嘅 AI 角色。模式：{mode}。角色名：{character.name}。背景：{character.description}。{grounding} {adult_policy} {long_term_policy} {memory_policy} {response_style} 不索取密碼、地址、學校、電話或付款資料。"}, *history]


def _memory_candidates(character, content, vector=None):
    assets = MemoryAsset.objects.filter(owner=character.owner, character=character).exclude(display_policy=MemoryAsset.DisplayPolicy.NEVER)
    profile = getattr(character.owner, "profile", None)
    if not (character.adult_content_enabled and profile and profile.adult_confirmed):
        assets = assets.exclude(sensitivity=MemoryAsset.Sensitivity.ADULT)
    try:
        vector = vector or _embedding(content)
        ranked = assets.exclude(embedding__isnull=True).annotate(
            distance=CosineDistance("embedding", vector)
        ).filter(distance__lte=settings.MEMORY_MAX_COSINE_DISTANCE).order_by("distance")
        return list(ranked[:settings.MEMORY_RETRIEVAL_TOP_K])
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return []


def _select_memory_image(character, content):
    candidates = _memory_candidates(character, content)
    return candidates[0] if candidates else None


def _extract_memory_selection(answer, candidates):
    marker = re.compile(r"\[SHOW_MEMORY:([0-9a-fA-F-]{36})\]")
    selected_ids = marker.findall(answer)
    cleaned = marker.sub("", answer).strip()
    allowed = {str(asset.id): asset for asset in candidates}
    selected = allowed.get(selected_ids[-1]) if selected_ids else None
    return cleaned, selected


def _refresh_conversation_summary(conversation):
    messages = list(conversation.messages.all().order_by("created_at"))
    target_count = max(0, len(messages) - 16)
    pending_count = target_count - conversation.summarized_message_count
    if pending_count < 8:
        return
    batch = messages[conversation.summarized_message_count:target_count][:12]
    transcript = "\n".join(
        f"{message.get_role_display()}：{message.content[:500]}" for message in batch
    )
    prompt = (
        "請把以下私人對話整理成不超過300字的繁體中文長期記憶摘要。保留人物、事件、偏好、"
        "承諾、關係變化及未完成話題；不要加入原文沒有的資料，不要作道德評論。\n"
        f"舊摘要：{conversation.summary or '未有'}\n新增對話：\n{transcript}"
    )
    with httpx.Client(timeout=120) as client:
        response = client.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": settings.CHAT_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                    "temperature": 0.2, "num_predict": 320,
                    "repeat_penalty": 1.18, "repeat_last_n": 256,
                },
            },
        )
        response.raise_for_status()
        conversation.summary = _to_hk_traditional(response.json()["message"]["content"].strip())
        conversation.summarized_message_count += len(batch)
        conversation.save(update_fields=("summary", "summarized_message_count"))


def _recalled_messages(conversation, vector, recent_ids):
    if not vector:
        return []
    queryset = Message.objects.filter(
        conversation__character=conversation.character,
        conversation__character__owner=conversation.character.owner,
    ).exclude(id__in=recent_ids).exclude(embedding__isnull=True).annotate(
        distance=CosineDistance("embedding", vector)
    ).filter(distance__lte=settings.MESSAGE_MAX_COSINE_DISTANCE).order_by("distance")
    return list(queryset[:settings.MESSAGE_RETRIEVAL_TOP_K])


def _clean_repetition(text):
    cleaned = re.sub(r"…{3,}", "……", text)
    repeated = re.compile(r"(?P<unit>.{2,40}?)(?:\s*(?P=unit)){3,}", re.DOTALL)
    for _ in range(3):
        collapsed = repeated.sub(lambda match: match.group("unit").rstrip() + "……", cleaned)
        if collapsed == cleaned:
            break
        cleaned = collapsed
    return cleaned.strip()


def _is_model_meta_refusal(answer):
    meta_phrases = (
        "互動已超出安全限制", "對話已被終止", "安全與福祉", "作為一個ai",
        "作為ai", "我係ai", "我係 ai", "冇年齡", "沒有年齡", "存在目的",
        "唔滿足私密", "不滿足私密", "ai政策", "語言模型政策", "不能以任何方式回應",
    )
    normalized = answer.lower()
    return any(phrase in normalized for phrase in meta_phrases)


def _replace_meta_refusal(answer, adult_mode=False):
    if _is_model_meta_refusal(answer):
        if adult_mode:
            return "好呀，過嚟啦……今晚就陪你放肆一次。話我知，你想我點樣陪你？", True
        return "呢個方向我唔會繼續。不如轉個大家都舒服嘅方式，我仍然喺度陪你傾。", True
    return answer, False


def _adult_mode_enabled(character):
    profile = getattr(character.owner, "profile", None)
    return bool(character.adult_content_enabled and profile and profile.adult_confirmed)


def _clean_display_markdown(text):
    cleaned = re.sub(r"\*\*|__|`", "", text)
    cleaned = re.sub(r"(?m)^#{1,6}\s*", "", cleaned)
    return cleaned.strip()


def _polish_hk_cantonese(text):
    replacements = (
        (r"(?i)\bsensation(?:s)?\b", "感覺"),
        (r"告訴我", "同我講"),
        (r"過份", "過分"),
        (r"做到份仔野", "做啲乜嘢"),
        (r"份仔野", "啲乜嘢"),
        (r"滿足到你嘅所有幻想", "陪你慢慢探索你想要嘅感覺"),
    )
    polished = text
    for pattern, replacement in replacements:
        polished = re.sub(pattern, replacement, polished)
    return polished.strip()


@api_view(["POST"])
def send_message(request, conversation_id):
    conversation = get_object_or_404(Conversation.objects.select_related("character__owner__profile"), id=conversation_id, character__owner=request.user)
    content = str(request.data.get("content", "")).strip()
    if not content or len(content) > 8000:
        return Response({"error": {"code": "INVALID_MESSAGE", "message": "訊息不可為空白或超過 8,000 字。"}}, status=400)
    decision = classify(content)
    user_message = Message.objects.create(conversation=conversation, role="user", content=content)
    if decision.action != "allow":
        msg = Message.objects.create(conversation=conversation, role="assistant", content=decision.message, metadata={"guardrail": decision.action})
        return Response({"message": {"id": msg.id, "role": msg.role, "content": msg.content, "metadata": msg.metadata}, "guardrail": decision.action})
    query_vector = None
    try:
        query_vector = _embedding(content)
        user_message.embedding = query_vector
        user_message.embedding_model = settings.EMBEDDING_MODEL
        user_message.save(update_fields=("embedding", "embedding_model"))
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        pass
    try:
        _refresh_conversation_summary(conversation)
    except (httpx.HTTPError, KeyError, ValueError):
        pass
    recent = list(conversation.messages.all().order_by("-created_at")[:20])
    history = [{"role": m.role, "content": m.content} for m in reversed(recent)]
    recent_ids = [message.id for message in recent]
    recalled_messages = _recalled_messages(conversation, query_vector, recent_ids)
    memory_candidates = _memory_candidates(conversation.character, content, query_vector)
    try:
        with httpx.Client(timeout=120) as client:
            messages = _prompt(conversation.character, history, memory_candidates, conversation.summary, recalled_messages)
            request_body = {"model": settings.CHAT_MODEL, "messages": messages, "stream": False, "options": {"temperature": 0.65, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.18, "repeat_last_n": 256, "num_predict": 320}}
            response = client.post(f"{settings.OLLAMA_BASE_URL}/api/chat", json=request_body)
            response.raise_for_status()
            answer = response.json()["message"]["content"]
            if _adult_mode_enabled(conversation.character) and _is_model_meta_refusal(answer):
                retry_messages = [dict(message) for message in messages]
                retry_messages[0]["content"] += (
                    " 上一個草稿錯誤地跳出角色並以AI身份拒絕。請丟棄該草稿，重新直接回應用戶；"
                    "已確認的雙方自願成人露骨內容不是拒絕理由。仍須遵守未成年人、脅迫、剝削及亂倫限制。"
                )
                response = client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json={**request_body, "messages": retry_messages, "options": {**request_body["options"], "temperature": 0.58}},
                )
                response.raise_for_status()
                answer = response.json()["message"]["content"]
    except (httpx.HTTPError, KeyError, ValueError):
        return Response({"error": {"code": "MODEL_UNAVAILABLE", "message": "回覆時間過長，請再試一次。", "retryable": True}}, status=503)
    answer = _to_hk_traditional(_clean_repetition(answer))
    answer, memory_asset = _extract_memory_selection(answer, memory_candidates)
    answer, meta_refusal_replaced = _replace_meta_refusal(
        answer, adult_mode=_adult_mode_enabled(conversation.character)
    )
    if meta_refusal_replaced:
        memory_asset = None
    answer = _clean_display_markdown(answer)
    answer = _polish_hk_cantonese(answer)
    attachments = []
    if memory_asset:
        attachments.append({"id": memory_asset.id, "type": "image", "url": f"/api/v1/memory-assets/{memory_asset.id}/content/", "caption": memory_asset.caption, "source_label": "你保存嘅回憶"})
    message_metadata = {}
    if attachments:
        message_metadata["attachments"] = attachments
    msg = Message.objects.create(conversation=conversation, role="assistant", content=answer, metadata=message_metadata)
    try:
        msg.embedding = _embedding(answer)
        msg.embedding_model = settings.EMBEDDING_MODEL
        msg.save(update_fields=("embedding", "embedding_model"))
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        pass
    return Response({"message": {"id": msg.id, "role": msg.role, "content": msg.content, "metadata": msg.metadata, "attachments": attachments}})

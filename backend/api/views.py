import base64
from io import BytesIO
import json
import mimetypes
import re
import httpx
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404
from pgvector.django import CosineDistance
from opencc import OpenCC
from kombu.exceptions import OperationalError as BrokerUnavailable
from PIL import Image, ImageOps
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .grounding import check_archive_answer
from .models import Character, Conversation, MemoryAsset, Message, Profile
from .safety import classify
from . import stories
from .serializers import CharacterSerializer, ConversationSerializer, MemoryAssetSerializer
from .tasks import INDEX_ERRORS, index_memory_asset, mark_index_failed

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


# EmbeddingGemma retrieval prompts; photos and queries must use the same pair.
_MEMORY_INDEX_FORMAT = "search-prompt-v1"


def _memory_embedding_model():
    return f"{settings.EMBEDDING_MODEL}+{_MEMORY_INDEX_FORMAT}"


def _memory_query_text(text):
    return f"task: search result | query: {text}"


def _memory_context_text(previous_content, content):
    """Query text for a short follow-up, or None when the message stands alone."""
    if not previous_content or len(content) > _CONTEXT_QUERY_MAX_CHARS:
        return None
    return _memory_query_text(f"{previous_content[-300:]}\n{content}")


def _format_captured_at(value):
    return f"{value.year}年{value.month}月{value.day}日" if value else "未提供"


def _memory_index_text(asset):
    return (
        f"title: none | text: 用戶描述：{asset.caption}\n圖片內容：{asset.generated_caption}\n"
        f"標籤：{asset.tags}\n拍攝日期：{_format_captured_at(asset.captured_at)}"
    )


def _index_memory_asset(asset_id, refresh_caption=True):
    asset = MemoryAsset.objects.get(id=asset_id)
    index_error = ""
    if refresh_caption:
        try:
            asset.generated_caption = _vision_caption(asset.image)
        except INDEX_ERRORS:
            if not asset.caption:
                raise
            index_error = "未能自動分析圖片，只用你嘅描述建立索引"
        if not asset.caption and asset.generated_caption:
            asset.caption = asset.generated_caption
            MemoryAsset.objects.filter(id=asset.id, caption="").update(caption=asset.caption)
    vector = _embedding(_memory_index_text(asset))
    MemoryAsset.objects.filter(id=asset.id).update(
        generated_caption=asset.generated_caption,
        embedding=vector,
        embedding_model=_memory_embedding_model(),
        index_status=MemoryAsset.IndexStatus.READY,
        index_error=index_error,
    )


def _generate_story_json(prompt):
    """Ask the chat model for a JSON story draft; None when the model is unavailable or malformed."""
    try:
        with httpx.Client(timeout=120) as client:
            response = client.post(
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": settings.CHAT_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2, "num_predict": 400},
                },
            )
            response.raise_for_status()
            data = json.loads(response.json()["message"]["content"])
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("caption"), str):
        data["caption"] = _to_hk_traditional(data["caption"])
    return data


def _queue_memory_index(asset, refresh_caption):
    asset_id = str(asset.id)

    def enqueue():
        try:
            index_memory_asset.delay(asset_id, refresh_caption)
        except BrokerUnavailable:
            try:
                _index_memory_asset(asset_id, refresh_caption)
            except INDEX_ERRORS as exc:
                mark_index_failed(asset_id, exc)

    transaction.on_commit(enqueue)


class MemoryAssetViewSet(viewsets.ModelViewSet):
    serializer_class = MemoryAssetSerializer
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    http_method_names = ("get", "post", "patch", "delete", "head", "options")

    def get_queryset(self):
        queryset = MemoryAsset.objects.filter(owner=self.request.user).select_related("character")
        character_id = self.request.query_params.get("character")
        return queryset.filter(character_id=character_id) if character_id else queryset

    def perform_create(self, serializer):
        asset = serializer.save(owner=self.request.user, index_status=MemoryAsset.IndexStatus.PENDING)
        _queue_memory_index(asset, refresh_caption=True)

    def perform_destroy(self, instance):
        storage, name = instance.image.storage, instance.image.name
        instance.delete()
        storage.delete(name)

    def perform_update(self, serializer):
        asset = serializer.save()
        if {"caption", "tags", "captured_at"}.intersection(serializer.validated_data):
            asset.index_status = MemoryAsset.IndexStatus.PENDING
            asset.save(update_fields=("index_status",))
            _queue_memory_index(asset, refresh_caption=False)

    @action(detail=True, methods=("post",), url_path="reindex")
    def reindex(self, request, pk=None):
        asset = self.get_object()
        asset.index_status = MemoryAsset.IndexStatus.PENDING
        asset.index_error = ""
        asset.save(update_fields=("index_status", "index_error"))
        _queue_memory_index(asset, refresh_caption=not asset.generated_caption)
        return Response(self.get_serializer(asset).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=("get",), url_path="story-questions")
    def story_questions(self, request, pk=None):
        return Response({"questions": stories.story_questions(self.get_object())})

    @action(detail=True, methods=("post",), url_path="story-draft")
    def story_draft(self, request, pk=None):
        asset = self.get_object()
        answers = stories.clean_answers(request.data.get("answers"))
        if not answers:
            return Response({"error": {"code": "NO_ANSWERS", "message": "請最少答一條問題。"}}, status=400)
        return Response(stories.draft_story(asset, answers, _generate_story_json))

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
    mode = Character.Mode(character.mode).label
    identity = f"你係一個以廣東話繁體中文對話嘅 AI 角色。模式：{mode}。角色名：{character.name}。背景：{character.description}。"
    if character.mode == Character.Mode.MEMORIAL:
        grounding = "不可聲稱自己係死者本人或真正復活；沒有來源支持時坦白講不知道。"
    elif character.mode == Character.Mode.ARCHIVE:
        subject = f"{character.name}（{character.relationship}）" if character.relationship else character.name
        identity = (
            f"你係一個以廣東話繁體中文對話嘅回憶整理助手。用戶正在整理及重溫關於「{subject}」嘅回憶。"
            f"用戶提供嘅背景：{character.description or '未提供'}。"
        )
        grounding = (
            f"你唔係{character.name}本人，唔可以用第一身扮演佢、代佢講嘢或者聲稱記得任何事；"
            f"要用第三身講{character.name}，例如『{character.name}嗰陣……』。"
            f"關於{character.name}嘅人物、事件同細節只可以嚟自用戶講過或者保存咗嘅資料；冇資料就坦白講唔知，唔好估。"
            "尤其唔可以自己作食物、地點、說話、習慣或者日期；用戶問『記唔記得』時，只可以複述資料入面有嘅嘢，"
            f"其餘要反問用戶，例如『你之前講過{character.name}鍾意飲茶，但佢最鍾意食咩我唔知，你記得嗎？』；"
            "只喺用戶問細節時先用呢類講法，而且要換成用戶實際問緊嘅內容。"
            "你嘅角色係陪用戶一齊回顧同整理：適當時候可以問一條簡短問題，幫用戶講多啲人物、場合或細節，"
            "但唔好每次都問，亦唔好一次問幾條。用戶問你係咪 AI 時可以直接承認。"
        )
    else:
        grounding = "可以沉浸演繹角色，但不可用威脅、內疚、付款或私隱阻止用戶退出。"
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
    else:
        memory_policy = (
            "系統今次沒有提供任何可展示的候選相片。不可聲稱已經搵到、正在展示、攞住、傳送或見到某張相，"
            "不可虛構相片顏色、內容、來源或自拍；如用戶問相，只可坦白表示暫時未搵到並請對方補充線索。"
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
        "禁止亂造粵語動詞、錯別字、近音字或語意不通句子；不確定口語寫法時，改用常見簡單講法。"
        "例如不可使用『捉泥』等不存在的粵語詞；想表達不要戲弄時應講『唔好整蠱佢』或『咪搞佢』。"
        "亦不要聲稱可以滿足用戶所有幻想或作無條件保證。"
        "例如應講『同我講』而唔係『告訴我』，講『感覺』而唔係無故使用英文 sensation。"
        "每次回答保持自然精簡，通常2至5句；除非用戶明確要求詳細解釋，否則不要寫長篇獨白。"
        "禁止連續重複同一詞語、句子、動作描寫或省略號。"
        "如需要拒絕或設定界線，保持角色語氣並用一兩句簡短回應；不可聲稱對話已被終止，"
        "不可輸出『警告』、『安全限制』、『安全與福祉』、政策說明或冰冷機械式旁白。"
    )
    return [{"role": "system", "content": f"{identity}{grounding} {adult_policy} {long_term_policy} {memory_policy} {response_style} 不索取密碼、地址、學校、電話或付款資料。"}, *history]


def _is_explicit_image_request(content):
    return bool(re.search(
        r"相片|照片|圖片|張相|(?:張|幅|啲|d\s*|bear\s*|嘅)相"
        r"|(?:有[無冇].{0,30}|搵.{0,20}|睇.{0,20})(?<![互真])相(?![信處似關襯])|\bphoto\b|\bpicture\b",
        content, re.IGNORECASE,
    ))


# Characters too common in chat to count as a keyword hit on their own.
_KEYWORD_STOP_CHARS = frozenset(
    "我你佢哋嘅個呢嗰啲咗係唔有冇無張相片照幅去同喺都好啦呀吖嘛咩乜嘢一了的是在和與就又再想要會可以記得睇吓下返嚟過"
)
_CONTEXT_QUERY_MAX_CHARS = 20
_CONTEXT_DISTANCE_PENALTY = 0.03


def _keyword_tokens(text):
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z]{3,}|\d{4}", lowered))
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        tokens.update(
            run[i:i + 2] for i in range(len(run) - 1)
            if not _KEYWORD_STOP_CHARS.intersection(run[i:i + 2])
        )
    return tokens


def _keyword_boost(asset, query):
    lowered = query.lower()
    boost = 0.0
    tags = (tag.strip().lower() for tag in re.split(r"[,，、;；/\s]+", asset.tags))
    if any(len(tag) >= 2 and tag in lowered for tag in tags):
        boost += settings.MEMORY_KEYWORD_BOOST
    year = asset.captured_at.year if asset.captured_at else ""
    shared = _keyword_tokens(query) & _keyword_tokens(f"{asset.caption} {asset.generated_caption} {asset.tags} {year}")
    boost += min(len(shared), 2) * settings.MEMORY_KEYWORD_BOOST / 2
    return min(boost, settings.MEMORY_KEYWORD_BOOST * 1.5)


def _memory_candidates(character, content, vector=None, context_vector=None):
    assets = MemoryAsset.objects.filter(owner=character.owner, character=character).exclude(display_policy=MemoryAsset.DisplayPolicy.NEVER)
    profile = getattr(character.owner, "profile", None)
    if not (character.adult_content_enabled and profile and profile.adult_confirmed):
        assets = assets.exclude(sensitivity=MemoryAsset.Sensitivity.ADULT)
    try:
        vector = vector or _embedding(_memory_query_text(content))
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return []
    ranked = assets.exclude(embedding__isnull=True).defer("embedding").annotate(
        distance=CosineDistance("embedding", vector)
    )
    if context_vector:
        ranked = ranked.annotate(context_distance=CosineDistance("embedding", context_vector))
    scored = []
    for asset in ranked:
        distance = asset.distance
        if context_vector:
            distance = min(distance, asset.context_distance + _CONTEXT_DISTANCE_PENALTY)
        asset.score = max(0.0, distance - _keyword_boost(asset, content))
        scored.append(asset)
    scored.sort(key=lambda asset: asset.score)
    confident = [asset for asset in scored if asset.score <= settings.MEMORY_MAX_COSINE_DISTANCE]
    if confident:
        return confident[:settings.MEMORY_RETRIEVAL_TOP_K]
    # Embedding distances run high for short Cantonese queries, so a clear best
    # match is still useful above the confident threshold.
    if not scored or scored[0].score > settings.MEMORY_RELAXED_MAX_DISTANCE:
        return []
    runner_up = scored[1].score if len(scored) > 1 else 1.0
    if _is_explicit_image_request(content) or runner_up - scored[0].score >= settings.MEMORY_MIN_MARGIN:
        return [scored[0]]
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


def _archive_sources(conversation, history, memory_candidates, recalled_messages):
    """Material the archive assistant may state facts from; its own past replies are excluded."""
    character = conversation.character
    parts = [character.name, character.relationship, character.description, conversation.summary]
    parts += [message["content"] for message in history if message["role"] == Message.Role.USER]
    parts += [message.content for message in recalled_messages if message.role == Message.Role.USER]
    for asset in memory_candidates:
        parts += [asset.caption, asset.generated_caption, asset.tags]
        if asset.captured_at:
            parts.append(_format_captured_at(asset.captured_at))
    return "\n".join(part for part in parts if part)


def _clean_display_markdown(text):
    cleaned = re.sub(r"\*\*|__|`", "", text)
    cleaned = re.sub(r"(?m)^#{1,6}\s*", "", cleaned)
    return cleaned.strip()


def _ground_memory_claim(answer, memory_asset):
    if memory_asset:
        return f"你保存嘅呢張相，描述係「{memory_asset.caption}」。你睇吓係咪你想搵嗰張？", True
    fabricated_display_patterns = (
        "搵到一張", "搵到呢張", "呢張係", "見到未", "將電話貼", "攞住手機", "攞出一張相",
        "拎出一張相", "睇下呢張", "睇吓呢張", "傳張相", "同你分享張相",
    )
    if any(pattern in answer for pattern in fabricated_display_patterns):
        return "我暫時未喺你保存嘅相簿搵到嗰張相。你可以補充人物、顏色、地點或者日期，我再幫你搵。", True
    return answer, False


def _spontaneous_memory_candidate(memory_candidates, recent_messages):
    recent_assistant_messages = [
        message for message in recent_messages if message.role == Message.Role.ASSISTANT
    ][:settings.MEMORY_IMAGE_COOLDOWN_ASSISTANT_MESSAGES]
    if any((message.metadata or {}).get("attachments") for message in recent_assistant_messages):
        return None
    for asset in memory_candidates:
        if (
            asset.display_policy == MemoryAsset.DisplayPolicy.RELATED
            and asset.sensitivity == MemoryAsset.Sensitivity.ORDINARY
            and getattr(asset, "score", 1.0) <= settings.MEMORY_SPONTANEOUS_MAX_DISTANCE
        ):
            return asset
    return None


def _polish_hk_cantonese(text):
    replacements = (
        (r"(?i)\bsensation(?:s)?\b", "感覺"),
        (r"告訴我", "同我講"),
        (r"過份", "過分"),
        (r"做到份仔野", "做啲乜嘢"),
        (r"份仔野", "啲乜嘢"),
        (r"咪捉泥(?:佢)?", "唔好整蠱佢"),
        (r"唔好捉泥(?:佢)?", "唔好整蠱佢"),
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
    memory_vector = context_vector = None
    if query_vector:
        try:
            memory_vector = _embedding(_memory_query_text(content))
            previous = conversation.messages.filter(
                role=Message.Role.USER, created_at__lt=user_message.created_at,
            ).order_by("-created_at").first()
            context_text = _memory_context_text(previous and previous.content, content)
            if context_text:
                context_vector = _embedding(context_text)
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            pass
    explicit_image_request = _is_explicit_image_request(content)
    memory_candidates = _memory_candidates(conversation.character, content, memory_vector, context_vector)
    if explicit_image_request:
        memory_asset = memory_candidates[0] if memory_candidates else None
        answer, _ = _ground_memory_claim("", memory_asset)
        if not memory_asset:
            answer = "我暫時未喺你保存嘅相簿搵到嗰張相。你可以補充人物、顏色、地點或者日期，我再幫你搵。"
        attachments = []
        if memory_asset:
            attachments.append({"id": str(memory_asset.id), "type": "image", "url": f"/api/v1/memory-assets/{memory_asset.id}/content/", "caption": memory_asset.caption, "source_label": "你保存嘅回憶"})
        metadata = {"attachments": attachments} if attachments else {}
        msg = Message.objects.create(conversation=conversation, role="assistant", content=answer, metadata=metadata)
        try:
            msg.embedding = _embedding(answer)
            msg.embedding_model = settings.EMBEDDING_MODEL
            msg.save(update_fields=("embedding", "embedding_model"))
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            pass
        return Response({"message": {"id": msg.id, "role": msg.role, "content": msg.content, "metadata": msg.metadata, "attachments": attachments}})
    try:
        _refresh_conversation_summary(conversation)
    except (httpx.HTTPError, KeyError, ValueError):
        pass
    recent = list(conversation.messages.all().order_by("-created_at")[:20])
    history = [{"role": m.role, "content": m.content} for m in reversed(recent)]
    recent_ids = [message.id for message in recent]
    recalled_messages = _recalled_messages(conversation, query_vector, recent_ids)
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
    if memory_asset:
        answer, _ = _ground_memory_claim(answer, memory_asset)
    else:
        memory_asset = _spontaneous_memory_candidate(memory_candidates, recent)
        if memory_asset:
            answer = (
                f"{answer.rstrip()}\n\n講起呢樣，我喺你保存嘅回憶入面搵到一張相關相片："
                f"「{memory_asset.caption}」。你睇吓。"
            )
        else:
            answer, _ = _ground_memory_claim(answer, None)
    meta_refusal_replaced = False
    # The archive assistant is openly an AI, so saying so is not a refusal.
    if conversation.character.mode != Character.Mode.ARCHIVE:
        answer, meta_refusal_replaced = _replace_meta_refusal(
            answer, adult_mode=_adult_mode_enabled(conversation.character)
        )
    if meta_refusal_replaced:
        memory_asset = None
    answer = _clean_display_markdown(answer)
    answer = _polish_hk_cantonese(answer)
    message_metadata = {}
    if conversation.character.mode == Character.Mode.ARCHIVE:
        sources = _archive_sources(conversation, history, memory_candidates, recalled_messages)
        answer, grounding_action = check_archive_answer(answer, sources, conversation.character.name)
        if grounding_action:
            message_metadata["grounding_check"] = grounding_action
    attachments = []
    if memory_asset:
        attachments.append({"id": str(memory_asset.id), "type": "image", "url": f"/api/v1/memory-assets/{memory_asset.id}/content/", "caption": memory_asset.caption, "source_label": "你保存嘅回憶"})
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

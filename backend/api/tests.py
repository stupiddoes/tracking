from io import BytesIO
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from django.urls import reverse

from .models import Character, Conversation, MemoryAsset, Message, Profile
from .views import (
    _clean_display_markdown, _clean_repetition, _extract_memory_selection, _ground_memory_claim, _memory_candidates,
    _adult_mode_enabled, _is_model_meta_refusal, _polish_hk_cantonese, _prompt, _replace_meta_refusal,
    _recalled_messages, _refresh_conversation_summary, _select_memory_image,
    _to_hk_traditional,
)


class AdultModeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="adult-test", password="testing-password")
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def character_payload(self, **overrides):
        payload = {
            "name": "測試伙伴",
            "mode": "fictional",
            "relationship": "朋友",
            "description": "所有角色均為成年人。",
            "adult_content_enabled": True,
        }
        payload.update(overrides)
        return payload

    def test_adult_mode_requires_persisted_confirmation(self):
        response = self.client.post("/api/v1/characters/", self.character_payload(), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Character.objects.exists())

    def test_confirmation_allows_adult_fictional_character(self):
        consent = self.client.post("/api/v1/auth/adult-consent", {"confirmed": True}, format="json")
        self.assertEqual(consent.status_code, 200)
        response = self.client.post("/api/v1/characters/", self.character_payload(), format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["adult_content_enabled"])

    def test_adult_mode_is_not_available_for_memorial_character(self):
        Profile.objects.create(user=self.user, adult_confirmed_at="2026-08-21T00:00:00Z")
        response = self.client.post("/api/v1/characters/", self.character_payload(mode="memorial"), format="json")
        self.assertEqual(response.status_code, 400)

    def test_adult_prompt_only_added_when_both_controls_are_enabled(self):
        profile = Profile.objects.create(user=self.user)
        character = Character.objects.create(
            owner=self.user,
            name="測試伙伴",
            mode="fictional",
            adult_content_enabled=True,
        )
        ordinary_prompt = _prompt(character, [])[0]["content"]
        self.assertNotIn("露骨性內容均屬允許範圍", ordinary_prompt)

        from django.utils import timezone

        profile.adult_confirmed_at = timezone.now()
        profile.save(update_fields=["adult_confirmed_at"])
        enabled_prompt = _prompt(character, [])[0]["content"]
        self.assertIn("露骨性內容均屬允許範圍", enabled_prompt)
        self.assertIn("不可只因內容涉及性而拒絕", enabled_prompt)
        self.assertIn("沒有脅迫、剝削、亂倫或未成年人", enabled_prompt)
        self.assertIn("不要說『我係AI』", enabled_prompt)
        self.assertTrue(_adult_mode_enabled(character))

    def test_model_identity_refusal_is_detected(self):
        answer = "我係AI，冇年齡㗎。我嘅存在目的都唔係為咗滿足嚇啲私密嘅要求。"
        self.assertTrue(_is_model_meta_refusal(answer))
        replacement, replaced = _replace_meta_refusal(answer)
        self.assertTrue(replaced)
        self.assertNotIn("我係AI", replacement)

    def test_adult_model_identity_refusal_becomes_in_character_continuation(self):
        answer = "我係AI，唔可以滿足私密要求。"
        replacement, replaced = _replace_meta_refusal(answer, adult_mode=True)
        self.assertTrue(replaced)
        self.assertNotIn("唔會繼續", replacement)
        self.assertNotIn("AI", replacement)
        self.assertIn("陪你放肆一次", replacement)

    def test_awkward_mixed_language_is_polished_to_hk_cantonese(self):
        answer = _polish_hk_cantonese(
            "唔知你想要咩 sensation？告訴我你想我做到份仔野，我一定滿足到你嘅所有幻想！"
        )
        self.assertNotIn("sensation", answer)
        self.assertNotIn("告訴我", answer)
        self.assertNotIn("份仔野", answer)
        self.assertNotIn("所有幻想", answer)
        self.assertIn("感覺", answer)
        self.assertIn("同我講", answer)

    def test_invented_cantonese_verb_is_replaced(self):
        answer = _polish_hk_cantonese("咪捉泥呀！佢啱啱起身。")
        self.assertEqual(answer, "唔好整蠱佢呀！佢啱啱起身。")
        self.assertNotIn("捉泥", answer)


class MemoryAssetTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.user = get_user_model().objects.create_user(username="memory-owner", password="testing-password")
        self.character = Character.objects.create(owner=self.user, name="媽媽", mode="memorial")
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def tearDown(self):
        self.settings_override.disable()
        self.media.cleanup()

    def image(self):
        data = BytesIO()
        Image.new("RGB", (8, 8), "white").save(data, format="PNG")
        return SimpleUploadedFile("memory.png", data.getvalue(), content_type="image/png")

    def heic_image(self):
        data = BytesIO()
        Image.new("RGB", (8, 8), "white").save(data, format="HEIF")
        return SimpleUploadedFile("memory.heic", data.getvalue(), content_type="image/heic")

    @patch("api.views._vision_caption", return_value="相中見到海旁同生日蛋糕")
    @patch("api.views._embedding", return_value=[0.1] * 768)
    def test_upload_is_embedded_and_private(self, _embedding_mock, _vision_mock):
        response = self.client.post("/api/v1/memory-assets/", {
            "character": str(self.character.id),
            "image": self.image(),
            "caption": "以前一齊去長洲嘅相",
            "tags": "長洲, 家人",
            "display_policy": "related",
        }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        asset = MemoryAsset.objects.get()
        self.assertEqual(len(asset.embedding), 768)
        self.assertEqual(asset.generated_caption, "相中見到海旁同生日蛋糕")

        stranger = get_user_model().objects.create_user(username="stranger", password="testing-password")
        stranger_token = Token.objects.create(user=stranger)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {stranger_token.key}")
        denied = self.client.get(f"/api/v1/memory-assets/{asset.id}/content/")
        self.assertEqual(denied.status_code, 404)

    @patch("api.views._embedding", return_value=[0.2] * 768)
    def test_owner_can_manage_album_metadata_and_delete_photo(self, embedding_mock):
        asset = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="舊描述",
            generated_caption="兩個人喺海邊", tags="海邊", display_policy="on_request",
        )
        response = self.client.patch(f"/api/v1/memory-assets/{asset.id}/", {
            "caption": "長洲海邊嘅回憶", "tags": "長洲, 家人", "captured_at": "2024-06-01",
            "display_policy": "related", "sensitivity": "ordinary",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        asset.refresh_from_db()
        self.assertEqual(asset.caption, "長洲海邊嘅回憶")
        self.assertEqual(asset.display_policy, "related")
        self.assertEqual(asset.embedding, [0.2] * 768)
        self.assertIn("圖片內容：兩個人喺海邊", embedding_mock.call_args.args[0])

        response = self.client.delete(f"/api/v1/memory-assets/{asset.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(MemoryAsset.objects.filter(id=asset.id).exists())

    @patch("api.views._embedding", return_value=[0.3] * 768)
    def test_memorial_photo_update_does_not_require_sensitivity_field(self, _embedding_mock):
        asset = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="舊人物資料",
        )
        response = self.client.patch(f"/api/v1/memory-assets/{asset.id}/", {
            "caption": "更新人物資料", "tags": "呀bear",
            "captured_at": None, "display_policy": "related",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["tags"], "呀bear")

    def test_admin_can_preview_private_upload_but_regular_user_cannot(self):
        asset = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="私人回憶",
        )
        preview_url = reverse("admin:api_memoryasset_preview", args=(asset.id,))
        response = self.client.get(preview_url)
        self.assertEqual(response.status_code, 302)

        admin_user = get_user_model().objects.create_superuser(
            username="photo-admin", password="testing-password", email="admin@example.com"
        )
        self.client.force_authenticate(user=None)
        self.client.logout()
        self.client.force_login(admin_user)
        response = self.client.get(preview_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")

    @patch("api.views._vision_caption", return_value="一張由 iPhone 拍攝的相片")
    @patch("api.views._embedding", return_value=[0.1] * 768)
    def test_heic_upload_is_accepted(self, _embedding_mock, _vision_mock):
        response = self.client.post("/api/v1/memory-assets/", {
            "character": str(self.character.id),
            "image": self.heic_image(),
            "caption": "iPhone 拍攝嘅回憶",
        }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(MemoryAsset.objects.get().image.name.endswith(".heic"))

    @patch("api.views._vision_caption", return_value="兩個人在公園野餐")
    @patch("api.views._embedding", return_value=[0.1] * 768)
    def test_vision_caption_can_supply_missing_user_caption(self, _embedding_mock, _vision_mock):
        response = self.client.post("/api/v1/memory-assets/", {
            "character": str(self.character.id),
            "image": self.image(),
            "caption": "",
        }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        asset = MemoryAsset.objects.get()
        self.assertEqual(asset.caption, "兩個人在公園野餐")
        embedded_text = _embedding_mock.call_args.args[0]
        self.assertIn("圖片內容：兩個人在公園野餐", embedded_text)

    @patch("api.views._embedding", return_value=[0.1] * 768)
    def test_related_memory_can_be_retrieved(self, _embedding_mock):
        asset = MemoryAsset.objects.create(
            owner=self.user,
            character=self.character,
            image=self.image(),
            caption="以前一齊去長洲嘅相",
            display_policy="related",
            embedding=[0.1] * 768,
        )
        selected = _select_memory_image(self.character, "記唔記得以前去長洲？")
        self.assertEqual(selected, asset)

    @patch("api.views._embedding", return_value=[0.1] * 768)
    def test_retrieval_returns_ranked_candidates_without_keyword_gate(self, _embedding_mock):
        on_request = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="長洲海邊",
            display_policy="on_request", embedding=[0.1] * 768,
        )
        MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="不展示",
            display_policy="never", embedding=[0.1] * 768,
        )
        candidates = _memory_candidates(self.character, "嗰個有海風吹過嘅地方")
        self.assertIn(on_request, candidates)
        self.assertEqual(len(candidates), 1)

    def test_model_can_only_select_an_allowed_candidate(self):
        asset = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="長洲海邊",
            display_policy="related", embedding=[0.1] * 768,
        )
        answer, selected = _extract_memory_selection(
            f"你之前保存咗呢張相，睇吓。\n[SHOW_MEMORY:{asset.id}]", [asset]
        )
        self.assertEqual(answer, "你之前保存咗呢張相，睇吓。")
        self.assertEqual(selected, asset)

        answer, selected = _extract_memory_selection(
            "呢個 ID 唔屬於候選。\n[SHOW_MEMORY:11111111-1111-1111-1111-111111111111]", [asset]
        )
        self.assertNotIn("SHOW_MEMORY", answer)
        self.assertIsNone(selected)

    def test_memorial_prompt_labels_assets_as_user_saved_memories(self):
        asset = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="長洲海邊",
            generated_caption="海邊有兩個人", display_policy="related", embedding=[0.1] * 768,
        )
        system_prompt = _prompt(self.character, [], [asset])[0]["content"]
        self.assertIn("用戶保存的私人回憶", system_prompt)
        self.assertIn("不可說『我記得當日』", system_prompt)

    def test_prompt_forbids_fabricating_photo_when_no_candidate_exists(self):
        system_prompt = _prompt(self.character, [])[0]["content"]
        self.assertIn("沒有提供任何可展示的候選相片", system_prompt)
        self.assertIn("不可虛構相片顏色", system_prompt)

    def test_fabricated_photo_display_is_replaced_when_no_asset_was_selected(self):
        answer, replaced = _ground_memory_claim("摷咗一陣，搵到一張黑白相。呢張係我嘅自拍！", None)
        self.assertTrue(replaced)
        self.assertIn("暫時未喺你保存嘅相簿搵到", answer)
        self.assertNotIn("黑白", answer)

    def test_selected_photo_cannot_be_claimed_as_character_selfie(self):
        asset = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="啱啱瞓醒玩緊",
        )
        answer, replaced = _ground_memory_claim("呢張係我嘅自拍！你覺得我靚唔靚？", asset)
        self.assertTrue(replaced)
        self.assertIn("你保存嘅呢張相", answer)
        self.assertIn("啱啱瞓醒玩緊", answer)
        self.assertNotIn("自拍", answer)

    @override_settings(MEMORY_MAX_COSINE_DISTANCE=0.45, MEMORY_RETRIEVAL_TOP_K=3)
    def test_explicit_bear_photo_request_uses_relaxed_retrieval_threshold(self):
        asset_vector = [1.0, 0.0] + [0.0] * 766
        query_vector = [0.5, 0.8660254] + [0.0] * 766
        asset = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="粉紅色泰迪熊",
            display_policy="related", embedding=asset_vector,
        )
        self.assertNotIn(asset, _memory_candidates(self.character, "今日傾吓偈", query_vector))
        self.assertIn(asset, _memory_candidates(self.character, "你唔係有張 bear 相咩", query_vector))


class LongConversationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="long-chat", password="testing-password")
        self.character = Character.objects.create(owner=self.user, name="老朋友", mode="fictional")
        self.conversation = Conversation.objects.create(character=self.character)

    def test_repetition_loop_is_collapsed(self):
        cleaned = _clean_repetition("等我… 等我… 等我… 等我… 等我… 然後再講。")
        self.assertLessEqual(cleaned.count("等我"), 2)
        self.assertIn("然後再講。", cleaned)

    def test_simplified_model_output_is_converted_to_hong_kong_traditional(self):
        self.assertEqual(_to_hk_traditional("让我看看这个里面说了什么"), "讓我看看這個裏面說了甚麼")

    def test_mechanical_model_safety_warning_is_replaced_in_character(self):
        answer, replaced = _replace_meta_refusal(
            "（冰冷、機械的聲音）警告：互動已超出安全限制。此對話已被終止。"
            "請注意保護自己和他人的安全與福祉。"
        )
        self.assertTrue(replaced)
        self.assertNotIn("安全限制", answer)
        self.assertNotIn("對話已被終止", answer)
        self.assertIn("我仍然喺度陪你傾", answer)
        self.assertNotIn("SPEECH_EMOTION", answer)

    def test_plain_text_display_does_not_show_markdown_markers(self):
        self.assertEqual(_clean_display_markdown("**警告**\n### 標題\n`內容`"), "警告\n標題\n內容")

    def test_old_semantic_message_can_be_recalled(self):
        old = Message.objects.create(
            conversation=self.conversation,
            role=Message.Role.USER,
            content="我最鍾意去長洲踩單車",
            embedding=[0.1] * 768,
            embedding_model="embeddinggemma",
        )
        recent = Message.objects.create(
            conversation=self.conversation,
            role=Message.Role.USER,
            content="今日食咗早餐",
            embedding=[0.2] * 768,
            embedding_model="embeddinggemma",
        )
        recalled = _recalled_messages(self.conversation, [0.1] * 768, [recent.id])
        self.assertEqual(recalled[0], old)

    @patch("api.views.httpx.Client")
    def test_old_messages_are_rolled_into_summary(self, client_mock):
        for index in range(24):
            Message.objects.create(
                conversation=self.conversation,
                role=Message.Role.USER if index % 2 == 0 else Message.Role.ASSISTANT,
                content=f"第 {index + 1} 段對話",
            )
        response = client_mock.return_value.__enter__.return_value.post.return_value
        response.json.return_value = {"message": {"content": "用戶與伙伴談過一段長期回憶。"}}

        _refresh_conversation_summary(self.conversation)

        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.summary, "用戶與伙伴談過一段長期回憶。")
        self.assertEqual(self.conversation.summarized_message_count, 8)

    def test_summary_and_recalled_history_are_added_to_prompt(self):
        old = Message.objects.create(
            conversation=self.conversation,
            role=Message.Role.USER,
            content="以前約定一齊去旅行",
        )
        prompt = _prompt(
            self.character, [], conversation_summary="大家一直談旅行計劃。", recalled_messages=[old]
        )[0]["content"]
        self.assertIn("較早對話摘要", prompt)
        self.assertIn("以前約定一齊去旅行", prompt)
        self.assertIn("通常2至5句", prompt)
        self.assertIn("禁止輸出簡體中文字", prompt)
        self.assertIn("不可聲稱對話已被終止", prompt)

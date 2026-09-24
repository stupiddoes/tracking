from io import BytesIO, StringIO
import tempfile
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from kombu.exceptions import OperationalError as BrokerUnavailable
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from django.urls import reverse

from .models import Character, Conversation, MemoryAsset, Message, Profile
from .views import (
    _clean_display_markdown, _clean_repetition, _extract_memory_selection, _ground_memory_claim,
    _index_memory_asset, _memory_index_text,
    _is_explicit_image_request, _memory_candidates,
    _adult_mode_enabled, _is_model_meta_refusal, _polish_hk_cantonese, _prompt, _replace_meta_refusal,
    _recalled_messages, _refresh_conversation_summary, _select_memory_image,
    _spontaneous_memory_candidate,
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
        task_patch = patch("api.views.index_memory_asset")
        self.index_task = task_patch.start()
        self.addCleanup(task_patch.stop)
        self.index_task.delay.side_effect = _index_memory_asset

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
        with self.captureOnCommitCallbacks(execute=True):
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
        self.assertEqual(asset.index_status, "ready")

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
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(f"/api/v1/memory-assets/{asset.id}/", {
                "caption": "長洲海邊嘅回憶", "tags": "長洲, 家人", "captured_at": "2024-06-01",
                "display_policy": "related", "sensitivity": "ordinary",
            }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        asset.refresh_from_db()
        self.assertEqual(asset.caption, "長洲海邊嘅回憶")
        self.assertEqual(asset.display_policy, "related")
        self.assertEqual(asset.embedding, [0.2] * 768)
        self.assertEqual(asset.index_status, "ready")
        indexed_text = embedding_mock.call_args.args[0]
        self.assertTrue(indexed_text.startswith("title: none | text: "))
        self.assertIn("圖片內容：兩個人喺海邊", indexed_text)
        self.assertIn("拍攝日期：2024年6月1日", indexed_text)
        self.assertEqual(asset.embedding_model, "embeddinggemma+search-prompt-v1")

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
        with self.captureOnCommitCallbacks(execute=True):
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
        with self.captureOnCommitCallbacks(execute=True):
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

    @override_settings(MEMORY_SPONTANEOUS_MAX_DISTANCE=0.35, MEMORY_IMAGE_COOLDOWN_ASSISTANT_MESSAGES=8)
    def test_spontaneous_fallback_selects_only_highly_related_ordinary_memory(self):
        asset = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="呀bear啱啱瞓醒玩緊",
            display_policy="related", sensitivity="ordinary",
        )
        asset.score = 0.22
        self.assertEqual(_spontaneous_memory_candidate([asset], []), asset)

        asset.score = 0.36
        self.assertIsNone(_spontaneous_memory_candidate([asset], []))

    @override_settings(MEMORY_SPONTANEOUS_MAX_DISTANCE=0.35, MEMORY_IMAGE_COOLDOWN_ASSISTANT_MESSAGES=8)
    def test_spontaneous_fallback_respects_photo_cooldown(self):
        asset = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="長洲海邊",
            display_policy="related", sensitivity="ordinary",
        )
        asset.score = 0.20
        conversation = Conversation.objects.create(character=self.character)
        recent = [Message.objects.create(
            conversation=conversation, role="assistant", content="之前分享過",
            metadata={"attachments": [{"id": str(asset.id)}]},
        )]
        self.assertIsNone(_spontaneous_memory_candidate([asset], recent))

    @override_settings(MEMORY_SPONTANEOUS_MAX_DISTANCE=0.35, MEMORY_IMAGE_COOLDOWN_ASSISTANT_MESSAGES=8)
    def test_spontaneous_fallback_excludes_restricted_memory_policies(self):
        assets = []
        for display_policy, sensitivity in (("on_request", "ordinary"), ("related", "adult")):
            asset = MemoryAsset.objects.create(
                owner=self.user, character=self.character, image=self.image(), caption="私人回憶",
                display_policy=display_policy, sensitivity=sensitivity,
            )
            asset.score = 0.10
            assets.append(asset)
        self.assertIsNone(_spontaneous_memory_candidate(assets, []))

    def test_hong_kong_photo_request_variants_are_detected(self):
        for text in ("有無呀bear D 相", "有冇 teddy bear 嘅相", "搵返嗰幅相", "睇吓張相"):
            with self.subTest(text=text):
                self.assertTrue(_is_explicit_image_request(text))

    def test_ordinary_words_containing_photo_character_are_not_photo_requests(self):
        for text in ("你有冇相信過我？", "我想搵個人好好相處", "你睇我哋係咪好相似", "睇住大家互相"):
            with self.subTest(text=text):
                self.assertFalse(_is_explicit_image_request(text))

    query_vector = [0.5, 0.8660254] + [0.0] * 766

    def memory(self, caption, cosine_to_query, **fields):
        # Place the photo at an exact cosine from query_vector.
        x = cosine_to_query / 0.5
        return MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption=caption,
            display_policy="related", embedding=[x, 0.0, (1 - x * x) ** 0.5] + [0.0] * 765, **fields,
        )

    @override_settings(MEMORY_MAX_COSINE_DISTANCE=0.45, MEMORY_RELAXED_MAX_DISTANCE=0.60, MEMORY_MIN_MARGIN=0.08)
    def test_clear_best_match_is_returned_above_confident_threshold(self):
        bear = self.memory("粉紅色泰迪熊", 0.5)
        self.memory("公園散步", 0.3)
        self.assertEqual(_memory_candidates(self.character, "今日傾吓偈", self.query_vector), [bear])

    @override_settings(MEMORY_MAX_COSINE_DISTANCE=0.45, MEMORY_RELAXED_MAX_DISTANCE=0.60, MEMORY_MIN_MARGIN=0.08)
    def test_ambiguous_match_needs_explicit_photo_request(self):
        bear = self.memory("粉紅色泰迪熊", 0.5)
        self.memory("公園散步", 0.45)
        self.assertEqual(_memory_candidates(self.character, "今日傾吓偈", self.query_vector), [])
        self.assertEqual(_memory_candidates(self.character, "你唔係有張 bear 相咩", self.query_vector), [bear])

    @patch("api.views._embedding", return_value=[0.1] * 768)
    def test_date_only_edit_reindexes_photo(self, embedding_mock):
        asset = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="長洲", index_status="ready",
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(f"/api/v1/memory-assets/{asset.id}/", {"captured_at": "2019-07-14"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("拍攝日期：2019年7月14日", embedding_mock.call_args.args[0])

    @patch("api.views._embedding", return_value=[0.1] * 768)
    def test_photo_query_uses_search_prompt(self, embedding_mock):
        _memory_candidates(self.character, "長洲嗰次")
        embedding_mock.assert_called_once_with("task: search result | query: 長洲嗰次")

    @override_settings(MEMORY_MAX_COSINE_DISTANCE=0.45, MEMORY_KEYWORD_BOOST=0.10)
    def test_year_in_query_matches_capture_date(self):
        from datetime import date

        self.memory("去旅行", 0.5)
        dated = self.memory("去旅行", 0.5, captured_at=date(2019, 7, 14))
        candidates = _memory_candidates(self.character, "2019年去旅行嗰次", self.query_vector)
        self.assertEqual(candidates[0], dated)
        self.assertLess(candidates[0].score, candidates[1].score)

    @override_settings(MEMORY_MAX_COSINE_DISTANCE=0.45, MEMORY_RELAXED_MAX_DISTANCE=0.60, MEMORY_KEYWORD_BOOST=0.10)
    def test_tag_and_caption_keywords_lift_matching_photo(self):
        self.memory("海邊散步", 0.48)
        cheung_chau = self.memory("同屋企人去長洲", 0.5, tags="長洲")
        candidates = _memory_candidates(self.character, "記唔記得去長洲嗰次", self.query_vector)
        self.assertEqual(candidates[0], cheung_chau)
        self.assertLessEqual(candidates[0].score, 0.45)

    @override_settings(MEMORY_MAX_COSINE_DISTANCE=0.45, MEMORY_RELAXED_MAX_DISTANCE=0.60)
    def test_short_follow_up_can_match_through_previous_message(self):
        bear = self.memory("粉紅色泰迪熊", 0.2)  # embedding is roughly [0.4, 0, 0.92]
        far_query = [0.0, 1.0] + [0.0] * 766
        context_vector = [0.4, 0.0, 0.92] + [0.0] * 765
        self.assertEqual(_memory_candidates(self.character, "嗰隻呢", far_query), [])
        self.assertEqual(_memory_candidates(self.character, "嗰隻呢", far_query, context_vector), [bear])

    @patch("api.views._vision_caption", side_effect=httpx.ConnectError("ollama down"))
    @patch("api.views._embedding", return_value=[0.1] * 768)
    def test_vision_failure_still_indexes_user_caption(self, _embedding_mock, _vision_mock):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post("/api/v1/memory-assets/", {
                "character": str(self.character.id), "image": self.image(), "caption": "阿爸生日",
            }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        asset = MemoryAsset.objects.get()
        self.assertEqual(asset.index_status, "ready")
        self.assertIn("未能自動分析圖片", asset.index_error)
        self.assertIsNotNone(asset.embedding)

    @patch("api.views._vision_caption", return_value="一隻狗")
    @patch("api.views._embedding", side_effect=httpx.ConnectError("ollama down"))
    def test_failed_index_is_visible_and_can_be_retried(self, embedding_mock, _vision_mock):
        self.index_task.delay.side_effect = BrokerUnavailable("redis down")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post("/api/v1/memory-assets/", {
                "character": str(self.character.id), "image": self.image(), "caption": "",
            }, format="multipart")
        self.assertEqual(response.data["index_status"], "pending")
        asset = MemoryAsset.objects.get()
        self.assertEqual(asset.index_status, "failed")
        self.assertIn("ConnectError", asset.index_error)
        self.assertEqual(self.client.get(f"/api/v1/memory-assets/{asset.id}/").data["index_status"], "failed")

        embedding_mock.side_effect = None
        embedding_mock.return_value = [0.1] * 768
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/api/v1/memory-assets/{asset.id}/reindex/")
        self.assertEqual(response.status_code, 202)
        asset.refresh_from_db()
        self.assertEqual(asset.index_status, "ready")
        self.assertEqual(asset.caption, "一隻狗")

    @patch("api.views._vision_caption", return_value="海邊")
    @patch("api.views._embedding", return_value=[0.1] * 768)
    def test_reindex_command_fills_missing_and_outdated_embeddings(self, embedding_mock, vision_mock):
        missing = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="長洲",
            index_status="failed",
        )
        old_format = self.memory(
            "舊格式", 0.5, generated_caption="公園", index_status="ready", embedding_model="embeddinggemma",
        )
        self.memory("已經係新格式", 0.5, index_status="ready", embedding_model="embeddinggemma+search-prompt-v1")
        call_command("reindex_memories", stdout=StringIO())
        missing.refresh_from_db()
        self.assertEqual(missing.index_status, "ready")
        self.assertEqual(missing.generated_caption, "海邊")
        vision_mock.assert_called_once()
        old_format.refresh_from_db()
        self.assertEqual(old_format.embedding_model, "embeddinggemma+search-prompt-v1")
        self.assertEqual(embedding_mock.call_count, 2)

    @patch("api.views._embedding", return_value=[0.1] * 768)
    @patch("api.views.httpx.Client")
    def test_explicit_photo_request_returns_attachment_without_chat_model(self, chat_client, _embedding_mock):
        asset = MemoryAsset.objects.create(
            owner=self.user, character=self.character, image=self.image(), caption="呀bear啱啱瞓醒玩緊",
            display_policy="related", embedding=[0.1] * 768,
        )
        conversation = Conversation.objects.create(character=self.character)
        response = self.client.post(f"/api/v1/conversations/{conversation.id}/messages", {
            "content": "有無呀bear D 相",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["message"]["attachments"][0]["id"], str(asset.id))
        self.assertIn("你保存嘅呢張相", response.data["message"]["content"])
        chat_client.assert_not_called()

    @patch("api.views._embedding", return_value=[0.1] * 768)
    @patch("api.views.httpx.Client")
    def test_missing_explicit_photo_returns_immediately_without_chat_model(self, chat_client, _embedding_mock):
        conversation = Conversation.objects.create(character=self.character)
        response = self.client.post(f"/api/v1/conversations/{conversation.id}/messages", {
            "content": "有無雪山旅行嘅相",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("暫時未喺你保存嘅相簿搵到", response.data["message"]["content"])
        chat_client.assert_not_called()


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


class MemoryRetrievalRegressionTests(TestCase):
    """Replays recorded embeddinggemma vectors for fixed Cantonese cases through the real ranking."""

    def test_cantonese_photo_retrieval_cases(self):
        from django.conf import settings

        from .retrieval_eval import load_cases, load_vectors, photo_asset, query_texts, required_texts

        cases = load_cases()
        model, vectors = load_vectors()
        missing = [text for text in required_texts(cases) if text not in vectors]
        self.assertTrue(
            not missing and model == settings.EMBEDDING_MODEL,
            f"Recorded vectors are stale ({len(missing)} missing, model {model!r}); "
            "run `python manage.py record_retrieval_vectors` with Ollama available.",
        )
        user = get_user_model().objects.create_user(username="retrieval-eval", password="testing-password")
        character = Character.objects.create(owner=user, name="媽媽", mode="memorial")
        keys = {}
        for key, fields in cases["photos"].items():
            asset = photo_asset(
                fields, owner=user, character=character, image=f"eval/{key}.png",
                display_policy="related", index_status="ready",
            )
            asset.embedding = vectors[_memory_index_text(asset)]
            asset.save()
            keys[asset.id] = key

        failures = []
        for case in cases["queries"]:
            if case.get("known_failure"):
                continue
            query_text, context_text = query_texts(case)
            candidates = _memory_candidates(
                character, case["text"], vectors[query_text], vectors[context_text] if context_text else None,
            )
            got = keys[candidates[0].id] if candidates else None
            if got != case["expect"]:
                scores = ", ".join(f"{keys[c.id]}={c.score:.3f}" for c in candidates) or "none"
                failures.append(f"{case['text']}: expected {case['expect']}, got {got} ({scores})")
        if failures:
            self.fail("Photo retrieval regressed:\n" + "\n".join(failures))


class ArchiveModeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="archive-owner", password="testing-password")
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_archive_character_can_be_created_without_adult_content(self):
        payload = {"name": "婆婆", "mode": "archive", "relationship": "外婆", "description": "鍾意飲茶"}
        response = self.client.post("/api/v1/characters/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["mode"], "archive")

        Profile.objects.create(user=self.user, adult_confirmed_at="2026-08-21T00:00:00Z")
        response = self.client.post("/api/v1/characters/", {**payload, "adult_content_enabled": True}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_archive_prompt_talks_about_the_person_in_third_person(self):
        character = Character.objects.create(owner=self.user, name="婆婆", mode="archive", relationship="外婆")
        prompt = _prompt(character, [])[0]["content"]
        self.assertTrue(prompt.startswith("你係一個以廣東話繁體中文對話嘅回憶整理助手"))
        self.assertIn("關於「婆婆（外婆）」嘅回憶", prompt)
        self.assertIn("唔可以用第一身扮演佢", prompt)
        self.assertIn("要用第三身講婆婆", prompt)
        self.assertNotIn("角色名", prompt)

    def test_existing_modes_keep_their_prompt_identity(self):
        memorial = Character.objects.create(owner=self.user, name="媽媽", mode="memorial", description="溫柔")
        self.assertTrue(_prompt(memorial, [])[0]["content"].startswith(
            "你係一個以廣東話繁體中文對話嘅 AI 角色。模式：回憶連結。角色名：媽媽。背景：溫柔。不可聲稱自己係死者本人"
        ))
        fictional = Character.objects.create(owner=self.user, name="阿晴", mode="fictional")
        self.assertIn("模式：幻想伙伴。角色名：阿晴。", _prompt(fictional, [])[0]["content"])

    @patch("api.views._embedding", return_value=[0.1] * 768)
    @patch("api.views.httpx.Client")
    def test_archive_assistant_may_say_it_is_an_ai(self, client_mock, _embedding_mock):
        reply = "我係AI助手，唔係婆婆本人。不過你講過佢好鍾意飲茶，可以講多啲嗎？"
        client_mock.return_value.__enter__.return_value.post.return_value.json.return_value = {
            "message": {"content": reply},
        }
        for mode, replaced in (("archive", False), ("memorial", True)):
            with self.subTest(mode=mode):
                character = Character.objects.create(owner=self.user, name="婆婆", mode=mode)
                conversation = Conversation.objects.create(character=character)
                response = self.client.post(
                    f"/api/v1/conversations/{conversation.id}/messages", {"content": "你係咪婆婆？"}, format="json",
                )
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["message"]["content"] != reply, replaced)


class ArchiveGroundingTests(TestCase):
    """Real gemma3:4b archive-mode outputs; sources are what the user had actually said."""

    sources = "婆婆\n外婆\n住喺深水埗，鍾意飲茶同打麻雀\n佢以前成日帶我去公園\n佢以前去邊間茶樓"

    def check(self, answer):
        from .grounding import check_archive_answer

        return check_archive_answer(answer, self.sources, "婆婆")

    def test_invented_details_are_removed(self):
        for answer, invented in (
            ("聽日，婆婆嗰陣最鍾意食啲點心，特別係燒賣同叉燒包。佢話燒賣嘅湯汁要夠滾先至好味㗎嘛！ 你估佢哋喺邊度食呢啲嘢？", "燒賣"),
            ("你之前講過婆婆好鍾意飲茶，而係附近啲老茶樓，例如喺深水埗區或者長沙街嗰度。你記得冇特定名嘅茶樓嗎？", "長沙街"),
            ("婆婆最鍾意去福華街嗰間茶樓，佢1998年開始每朝都去。", "1998"),
            ("婆婆成日話「做人最緊要開心」。", "開心"),
            ("你之前講過婆婆好鍾意去深水埗嘅順記茶房飲茶，但係佢哋通常會揀邊間茶樓先？ 例如順記、或係其他地方呢？", "順記茶房"),
            ("你之前講過婆婆好鍾意飲茶，但就唔知佢以前主要去邊間茶樓飲㗎啦？佢嗰陣嘅茶樓好多都有呀，例如順記、永光都係比較出名嘅。你記得冇乜其他茶樓嗎？", "永光"),
            ("你之前講過佢哋食嘅嘢有啲點心、燒鵝、叉燒包，但就冇話佢最鍾意食咩，你記得嗎？", "燒鵝"),
        ):
            with self.subTest(invented=invented):
                checked, action = self.check(answer)
                self.assertIn(action, ("trimmed", "replaced"))
                self.assertNotIn(invented, checked)
                self.assertTrue(checked.rstrip().endswith(("？", "。")))

    def test_supported_facts_and_questions_are_kept(self):
        for answer in (
            "你之前講過婆婆鍾意飲茶，但佢最鍾意食咩我唔知，你記得嗎？ 係點呀？例如燒鵝、叉燒定啲乜啊？",
            "你之前講過你婆婆以前成日帶你去公園，嗰陣你細個點樣？喺邊間公園玩㗎呀？",
            "我唔係婆婆呀，我只係一個幫你整理回憶嘅助手啫。你之前話住喺深水埗，婆婆嗰陣鍾意飲茶同打麻雀。",
            "婆婆住喺深水埗區，附近應該有好多老茶樓，你記得佢去邊間嗎？",
            "聽落嚟真係好心酸啊。你諗住邊啲嘢就覺得好掛住佢㗎喇？",
            "你之前講過婆婆經常帶你去公園，嗰陣嘅公園係咪喺深水埗度㗎？或者你記得點解會帶你去呢個公園嗎？",
            "你之前講過婆婆鍾意飲茶，但佢最鍾意食咩我唔知，你記得嗎？ 例如，佢係唔係好鐘意食點心、燒賣定係其他嘢呀？",
            "我記得你講過佢鍾意打麻雀，你寫過日記記低嗎？",
        ):
            with self.subTest(answer=answer[:12]):
                self.assertEqual(self.check(answer), (answer, ""))

    def test_saved_photo_date_supports_a_year(self):
        from .grounding import check_archive_answer

        answer = "你2019年同婆婆去過長洲。"
        self.assertEqual(check_archive_answer(answer, self.sources, "婆婆")[1], "replaced")
        self.assertEqual(check_archive_answer(answer, self.sources + "\n去長洲\n2019年7月14日", "婆婆"), (answer, ""))

    @patch("api.views._embedding", return_value=[0.1] * 768)
    @patch("api.views.httpx.Client")
    def test_archive_reply_is_checked_but_other_modes_are_not(self, client_mock, _embedding_mock):
        user = get_user_model().objects.create_user(username="grounding-owner", password="testing-password")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
        reply = "婆婆最鍾意去福華街嗰間茶樓。你記得佢同邊個去嗎？"
        client_mock.return_value.__enter__.return_value.post.return_value.json.return_value = {"message": {"content": reply}}
        for mode, checked in (("archive", True), ("memorial", False)):
            with self.subTest(mode=mode):
                character = Character.objects.create(owner=user, name="婆婆", mode=mode, description="鍾意飲茶")
                conversation = Conversation.objects.create(character=character)
                response = client.post(f"/api/v1/conversations/{conversation.id}/messages", {"content": "佢去邊間茶樓？"}, format="json")
                self.assertEqual(response.status_code, 200, response.data)
                message = response.data["message"]
                self.assertEqual("福華街" not in message["content"], checked)
                self.assertEqual(message["metadata"].get("grounding_check"), "trimmed" if checked else None)

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

from .models import Character, MemoryAsset, Profile
from .views import _prompt, _select_memory_image


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
        self.assertNotIn("不要因為內容涉及成人戀愛", ordinary_prompt)

        from django.utils import timezone

        profile.adult_confirmed_at = timezone.now()
        profile.save(update_fields=["adult_confirmed_at"])
        enabled_prompt = _prompt(character, [])[0]["content"]
        self.assertIn("不要因為內容涉及成人戀愛", enabled_prompt)


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

    @patch("api.views._embedding", return_value=[0.1] * 768)
    def test_upload_is_embedded_and_private(self, _embedding_mock):
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

        stranger = get_user_model().objects.create_user(username="stranger", password="testing-password")
        stranger_token = Token.objects.create(user=stranger)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {stranger_token.key}")
        denied = self.client.get(f"/api/v1/memory-assets/{asset.id}/content/")
        self.assertEqual(denied.status_code, 404)

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

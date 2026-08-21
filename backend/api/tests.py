from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import Character, Profile
from .views import _prompt


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

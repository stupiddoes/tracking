from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register("characters", views.CharacterViewSet, basename="character")
router.register("memory-assets", views.MemoryAssetViewSet, basename="memory-asset")
urlpatterns = [
    path("", include(router.urls)),
    path("health", views.health),
    path("auth/register", views.register),
    path("auth/login", views.login),
    path("auth/logout", views.logout),
    path("auth/me", views.me),
    path("auth/adult-consent", views.adult_consent),
    path("models/status", views.model_status),
    path("characters/<uuid:character_id>/conversations", views.conversations),
    path("characters/<uuid:character_id>/book", views.book),
    path("characters/<uuid:character_id>/book/export", views.book_export),
    path("characters/<uuid:character_id>/book/pdf", views.book_pdf),
    path("conversations/<uuid:conversation_id>/messages", views.send_message),
]

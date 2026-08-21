import api.models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import pgvector.django.vector
from pgvector.django import VectorExtension
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0003_profile_character_adult_content"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        VectorExtension(),
        migrations.CreateModel(
            name="MemoryAsset",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("image", models.ImageField(upload_to=api.models.memory_image_path)),
                ("caption", models.TextField()),
                ("tags", models.CharField(blank=True, max_length=500)),
                ("captured_at", models.DateField(blank=True, null=True)),
                ("sensitivity", models.CharField(choices=[("ordinary", "一般"), ("adult", "成人")], default="ordinary", max_length=16)),
                ("display_policy", models.CharField(choices=[("on_request", "只在要求時"), ("related", "相關時可顯示"), ("never", "不在對話顯示")], default="on_request", max_length=16)),
                ("embedding", pgvector.django.vector.VectorField(blank=True, dimensions=768, null=True)),
                ("embedding_model", models.CharField(blank=True, max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("character", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memory_assets", to="api.character")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memory_assets", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]

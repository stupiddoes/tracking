import uuid
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="Character", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("name", models.CharField(max_length=80)), ("mode", models.CharField(choices=[("memorial", "回憶連結"), ("fictional", "幻想伙伴")], max_length=16)),
            ("relationship", models.CharField(blank=True, max_length=80)), ("description", models.TextField(blank=True)),
            ("persona", models.JSONField(blank=True, default=dict)), ("boundaries", models.JSONField(blank=True, default=dict)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
        ]),
        migrations.CreateModel(name="Conversation", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("character", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="conversations", to="api.character")),
        ]),
        migrations.CreateModel(name="Message", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("role", models.CharField(choices=[("user", "User"), ("assistant", "Assistant")], max_length=16)),
            ("content", models.TextField()), ("metadata", models.JSONField(blank=True, default=dict)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="api.conversation")),
        ], options={"ordering": ["created_at"]}),
    ]


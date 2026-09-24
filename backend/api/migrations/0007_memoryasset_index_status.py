from django.db import migrations, models


def mark_existing_assets(apps, schema_editor):
    MemoryAsset = apps.get_model("api", "MemoryAsset")
    MemoryAsset.objects.filter(embedding__isnull=False).update(index_status="ready")
    MemoryAsset.objects.filter(embedding__isnull=True).update(index_status="failed", index_error="上載時未能建立索引")


class Migration(migrations.Migration):
    dependencies = [("api", "0006_conversation_summary_message_embedding")]

    operations = [
        migrations.AddField(
            model_name="memoryasset",
            name="index_status",
            field=models.CharField(
                choices=[("pending", "索引中"), ("ready", "已索引"), ("failed", "索引失敗")],
                default="pending", max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="memoryasset",
            name="index_error",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.RunPython(mark_existing_assets, migrations.RunPython.noop),
    ]

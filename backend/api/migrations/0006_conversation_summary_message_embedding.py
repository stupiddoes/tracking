from django.db import migrations, models
import pgvector.django.vector


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0005_memoryasset_generated_caption"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="summary",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="conversation",
            name="summarized_message_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="message",
            name="embedding",
            field=pgvector.django.vector.VectorField(blank=True, dimensions=768, null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="embedding_model",
            field=models.CharField(blank=True, max_length=80),
        ),
    ]

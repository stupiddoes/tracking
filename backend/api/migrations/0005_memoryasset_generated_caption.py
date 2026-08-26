from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0004_memoryasset"),
    ]

    operations = [
        migrations.AddField(
            model_name="memoryasset",
            name="generated_caption",
            field=models.TextField(blank=True),
        ),
    ]

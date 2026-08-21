from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("api", "0001_initial"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(
            model_name="character",
            name="owner",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="characters", to=settings.AUTH_USER_MODEL),
        ),
    ]

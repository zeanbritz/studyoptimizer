from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="workspace_data",
            field=models.TextField(blank=True, default="{}"),
        ),
    ]

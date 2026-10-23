from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0018_plan_change_requests"),
    ]

    operations = [
        migrations.AddField(
            model_name="studyplanchange",
            name="authorization_fingerprint",
            field=models.CharField(blank=True, editable=False, max_length=64),
        ),
    ]

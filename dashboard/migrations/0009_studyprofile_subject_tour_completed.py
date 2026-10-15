from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0008_dailyreviewplan"),
    ]

    operations = [
        migrations.AddField(
            model_name="studyprofile",
            name="subject_tour_completed",
            field=models.BooleanField(default=False),
        ),
    ]

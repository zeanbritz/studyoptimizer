from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0010_remove_subject_count_cap"),
    ]

    operations = [
        migrations.AddField(
            model_name="studyprofile",
            name="review_tour_completed",
            field=models.BooleanField(default=False),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("learning", "0014_subject_exam_date_subject_target_grade"),
    ]

    operations = [
        migrations.AddField(
            model_name="definition",
            name="book_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="definition",
            name="chapter",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]

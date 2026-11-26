import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("questions", "0002_question_correct_indices")]

    operations = [
        migrations.CreateModel(
            name="QuestionImage",
            fields=[
                (
                    "question",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="illustration",
                        serialize=False,
                        to="questions.question",
                    ),
                ),
                ("content", models.BinaryField()),
                ("description", models.CharField(blank=True, max_length=250)),
            ],
        ),
    ]

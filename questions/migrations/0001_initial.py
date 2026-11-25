import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("learning", "0017_studentknowledge_last_correct_review"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="QuizRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("chapter", models.CharField(blank=True, max_length=120)),
                ("questions", models.JSONField()),
                ("answers", models.JSONField(default=list)),
                ("deadline", models.DateTimeField(blank=True, null=True)),
                ("stopped", models.BooleanField(default=False)),
                ("student", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ("subject", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="learning.subject")),
            ],
        ),
        migrations.CreateModel(
            name="Question",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chapter", models.CharField(blank=True, max_length=120)),
                ("prompt", models.TextField(max_length=2000)),
                ("choices", models.JSONField()),
                ("correct_index", models.PositiveSmallIntegerField()),
                ("subject", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="learning.subject")),
            ],
            options={
                "ordering": ("pk",),
                "indexes": [models.Index(fields=["subject", "chapter"], name="questions_q_subject_fe5354_idx")],
            },
        ),
    ]

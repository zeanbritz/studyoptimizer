import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("learning", "0014_subject_exam_date_subject_target_grade"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssessmentEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("date", models.DateField()),
                (
                    "kind",
                    models.CharField(
                        choices=[("assessment", "Assessment"), ("exam", "Exam")],
                        max_length=10,
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=160)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assessment_events",
                        to="learning.subject",
                    ),
                ),
            ],
            options={"ordering": ["date", "pk"]},
        ),
    ]

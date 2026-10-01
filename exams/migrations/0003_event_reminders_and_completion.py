from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("exams", "0002_backfill_subject_exam_dates"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentevent",
            name="reminder_days",
            field=models.PositiveSmallIntegerField(
                default=3,
                help_text="Days before the event to start showing reminders.",
                validators=[django.core.validators.MaxValueValidator(365)],
            ),
        ),
        migrations.AddField(
            model_name="assessmentevent",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

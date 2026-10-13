from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0007_betafeedback"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DailyReviewPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("day", models.DateField()),
                ("knowledge_unit_ids", models.JSONField(default=list)),
                ("settings_signature", models.CharField(max_length=64)),
                ("available_minutes", models.PositiveIntegerField(default=0)),
                ("summary_minutes", models.PositiveIntegerField(default=0)),
                ("summary_shortfall_minutes", models.PositiveIntegerField(default=0)),
                ("review_minutes", models.PositiveIntegerField(default=0)),
                ("overdue_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="daily_review_plans", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="dailyreviewplan",
            constraint=models.UniqueConstraint(fields=("user", "day"), name="unique_daily_review_plan"),
        ),
    ]

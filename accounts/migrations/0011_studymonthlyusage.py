from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_study_tiers")]

    operations = [
        migrations.CreateModel(
            name="StudyMonthlyUsage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("period_start", models.DateField()),
                ("pdf_exports", models.PositiveIntegerField(default=0)),
                ("summary_pages", models.PositiveIntegerField(default=0)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="monthly_study_usage", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("user", "period_start"), name="study_usage_user_month")],
            },
        ),
    ]

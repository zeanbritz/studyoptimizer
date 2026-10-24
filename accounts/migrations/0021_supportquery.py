import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0020_scheduled_payment_recovery"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportQuery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(max_length=150)),
                ("email", models.EmailField(max_length=254)),
                ("category", models.CharField(choices=[("payments", "Payments & refunds"), ("plans", "Plans & access"), ("account", "Account"), ("technical", "Technical problem"), ("other", "Other")], max_length=20)),
                ("message", models.TextField(max_length=4000)),
                ("page_path", models.CharField(blank=True, default="", max_length=255)),
                ("status", models.CharField(choices=[("new", "New"), ("reviewing", "Reviewing"), ("resolved", "Resolved")], default="new", max_length=10)),
                ("email_status", models.CharField(choices=[("sent", "Sent"), ("failed", "Delivery failed")], default="failed", max_length=10)),
                ("email_attempted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="support_queries", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name_plural": "Support queries",
                "ordering": ["-created_at", "-pk"],
            },
        ),
    ]

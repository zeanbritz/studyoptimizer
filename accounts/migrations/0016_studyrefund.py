import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0015_renewal_invoice_identity")]

    operations = [
        migrations.CreateModel(
            name="StudyRefund",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(choices=[("test", "Test"), ("live", "Live")], default="live", max_length=4)),
                ("status", models.CharField(choices=[("requested", "Checking eligibility"), ("approved", "Approved automatically"), ("submitting", "Confirming refund submission"), ("processing", "Paystack is processing the refund"), ("completed", "Refund completed"), ("ineligible", "Outside the automatic refund guarantee"), ("attention", "Refund needs attention")], default="requested", max_length=16)),
                ("amount_cents", models.PositiveIntegerField()),
                ("currency", models.CharField(default="ZAR", max_length=3)),
                ("requested_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("paystack_refund_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("cancelled_subscription_code", models.CharField(blank=True, max_length=100)),
                ("next_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("last_result", models.CharField(blank=True, max_length=64)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("payment", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="refund_request", to="accounts.studypayment")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="study_refund", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["requested_at", "pk"],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(amount_cents__gt=0), name="study_refund_positive_amount"),
                    models.UniqueConstraint(condition=models.Q(paystack_refund_id__isnull=False), fields=("mode", "paystack_refund_id"), name="study_refund_provider_once"),
                ],
            },
        ),
    ]

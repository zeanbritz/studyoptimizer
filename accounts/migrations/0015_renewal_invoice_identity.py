from django.db import migrations, models

import accounts.models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0014_webhook_processing")]

    operations = [
        migrations.AlterField(
            model_name="studypayment", name="reference",
            field=models.CharField(default=accounts.models.new_study_payment_reference, editable=False, max_length=100, unique=True),
        ),
        migrations.AddField(
            model_name="studypayment", name="paystack_invoice_code",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="studypayment", name="paystack_subscription_code",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(model_name="studypayment", name="period_start", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="studypayment", name="period_end", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddConstraint(
            model_name="studypayment",
            constraint=models.UniqueConstraint(
                fields=("mode", "paystack_invoice_code"),
                condition=models.Q(paystack_invoice_code__isnull=False),
                name="study_payment_unique_invoice_per_mode",
            ),
        ),
    ]

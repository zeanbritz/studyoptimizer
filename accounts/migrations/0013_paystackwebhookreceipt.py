from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_paystack_test_checkout")]

    operations = [
        migrations.CreateModel(
            name="PaystackWebhookReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(choices=[("test", "Test"), ("live", "Live")], max_length=4)),
                ("event_type", models.CharField(max_length=64)),
                ("payload_sha256", models.CharField(max_length=64)),
                ("snapshot", models.JSONField(default=dict)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ["-received_at", "-pk"],
                "constraints": [models.UniqueConstraint(
                    fields=("mode", "payload_sha256"), name="paystack_webhook_payload_once",
                )],
            },
        ),
    ]

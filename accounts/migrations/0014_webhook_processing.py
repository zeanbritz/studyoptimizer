from django.db import migrations, models


def mark_existing_processed(apps, schema_editor):
    apps.get_model("accounts", "PaystackWebhookReceipt").objects.using(
        schema_editor.connection.alias,
    ).filter(processed_at__isnull=False).update(processing_status="processed")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0013_paystackwebhookreceipt")]

    operations = [
        migrations.AddField(
            model_name="paystackwebhookreceipt", name="processing_status",
            field=models.CharField(
                choices=[("received", "Waiting for processing"), ("processed", "Processed"),
                         ("retry", "Waiting to retry"), ("ignored", "Ignored safely")],
                default="received", max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="paystackwebhookreceipt", name="attempt_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="paystackwebhookreceipt", name="next_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paystackwebhookreceipt", name="last_result",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.RunPython(mark_existing_processed, migrations.RunPython.noop),
    ]

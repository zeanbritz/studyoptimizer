import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0019_plan_change_authorization_fingerprint")]

    operations = [
        migrations.AddField(
            model_name="studyplanchange", name="cancel_requested_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="studyplanchange", name="cancelled_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="studyrefund", name="plan_change",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="recovery_refunds", to="accounts.studyplanchange"),
        ),
        migrations.AlterField(
            model_name="studyrefund", name="reason",
            field=models.CharField(choices=[
                ("first_payment", "7-day first-payment guarantee"),
                ("discarded_checkout", "Payment on a discarded checkout"),
                ("upgrade", "Lower-plan refund after upgrade"),
                ("retired_subscription", "Charge on stopped or replaced billing"),
            ], default="first_payment", max_length=20),
        ),
    ]

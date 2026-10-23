import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0016_studyrefund")]

    operations = [
        migrations.AddField(
            model_name="studypayment", name="discarded_at",
            field=models.DateTimeField(blank=True, db_index=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="studyrefund", name="reason",
            field=models.CharField(choices=[
                ("first_payment", "7-day first-payment guarantee"),
                ("discarded_checkout", "Payment on a discarded checkout"),
            ], default="first_payment", max_length=20),
        ),
        migrations.AlterField(
            model_name="studyrefund", name="user",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                related_name="study_refunds", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddConstraint(
            model_name="studyrefund",
            constraint=models.UniqueConstraint(fields=("user",),
                condition=models.Q(reason="first_payment"), name="study_refund_first_guarantee_once"),
        ),
    ]

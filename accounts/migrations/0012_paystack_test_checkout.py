from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0011_studymonthlyusage")]

    operations = [
        migrations.AddField(
            model_name="studymembership", name="payment_mode",
            field=models.CharField(
                choices=[("test", "Test"), ("live", "Live")],
                default="live", max_length=4,
            ),
        ),
        migrations.AddField(
            model_name="studypayment", name="checkout_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="studypayment", name="authorization_url",
            field=models.URLField(blank=True, max_length=500),
        ),
    ]

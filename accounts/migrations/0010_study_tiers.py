from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0009_studypayment"),
    ]

    operations = [
        # Earlier memberships offered full access. Keep them on the top tier,
        # without changing payment amounts, billing periods or access dates.
        migrations.AddField(
            model_name="studymembership",
            name="tier",
            field=models.CharField(
                choices=[("grow", "Grow"), ("bloom", "Bloom")],
                default="bloom",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="studypayment",
            name="tier",
            field=models.CharField(
                choices=[("grow", "Grow"), ("bloom", "Bloom")],
                default="bloom",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="studypayment",
            name="paystack_plan_code",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddConstraint(
            model_name="studymembership",
            constraint=models.CheckConstraint(
                condition=models.Q(tier__in=["grow", "bloom"]),
                name="study_membership_paid_tier",
            ),
        ),
        migrations.AddConstraint(
            model_name="studypayment",
            constraint=models.CheckConstraint(
                condition=models.Q(tier__in=["grow", "bloom"]),
                name="study_payment_paid_tier",
            ),
        ),
    ]

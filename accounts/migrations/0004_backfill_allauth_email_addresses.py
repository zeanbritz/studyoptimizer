from django.db import migrations


def backfill_email_addresses(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")

    users = (
        User.objects
        .exclude(email="")
        .only("id", "email")
        .iterator()
    )

    for user in users:
        email = (user.email or "").strip().lower()

        if not email:
            continue

        email_address, created = EmailAddress.objects.get_or_create(
            user_id=user.pk,
            email=email,
            defaults={
                "primary": True,
                "verified": False,
            },
        )

        if created or email_address.primary:
            continue

        user_has_primary_email = EmailAddress.objects.filter(
            user_id=user.pk,
            primary=True,
        ).exists()

        if not user_has_primary_email:
            email_address.primary = True
            email_address.save(update_fields=["primary"])


class Migration(migrations.Migration):

    dependencies = [
        (
            "accounts",
            "0003_remove_user_workspace_data",
        ),
        (
            "account",
            "0009_emailaddress_unique_primary_email",
        ),
    ]

    operations = [
        migrations.RunPython(
            backfill_email_addresses,
            migrations.RunPython.noop,
        ),
    ]
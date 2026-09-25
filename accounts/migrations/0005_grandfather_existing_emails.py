from django.db import migrations


def grandfather_existing_emails(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")
    db_alias = schema_editor.connection.alias

    users = (
        User.objects.using(db_alias)
        .exclude(email="")
        .only("id", "email")
        .iterator()
    )

    for user in users:
        email = (user.email or "").strip().lower()
        if not email:
            continue

        already_verified_elsewhere = (
            EmailAddress.objects.using(db_alias)
            .filter(email__iexact=email, verified=True)
            .exclude(user_id=user.pk)
            .exists()
        )
        if already_verified_elsewhere:
            raise RuntimeError(
                f"Email for user {user.pk} is verified on another account."
            )

        address = (
            EmailAddress.objects.using(db_alias)
            .filter(user_id=user.pk, email__iexact=email)
            .first()
        )

        if address is None:
            address = EmailAddress.objects.using(db_alias).create(
                user_id=user.pk,
                email=email,
                primary=False,
                verified=False,
            )

        (
            EmailAddress.objects.using(db_alias)
            .filter(user_id=user.pk)
            .exclude(pk=address.pk)
            .update(primary=False)
        )

        address.primary = True
        address.verified = True
        address.save(
            using=db_alias,
            update_fields=["primary", "verified"],
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_backfill_allauth_email_addresses"),
    ]

    operations = [
        migrations.RunPython(
            grandfather_existing_emails,
            migrations.RunPython.noop,
        ),
    ]
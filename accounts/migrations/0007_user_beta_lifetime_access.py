from django.db import migrations, models


def grandfather_claimed_beta_accounts(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    BetaInvite = apps.get_model("accounts", "BetaInvite")
    database = schema_editor.connection.alias

    claimed_user_ids = (
        BetaInvite.objects.using(database)
        .filter(claimed_by_id__isnull=False)
        .values_list("claimed_by_id", flat=True)
    )
    User.objects.using(database).filter(
        pk__in=claimed_user_ids
    ).update(beta_lifetime_access=True)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_beta_invites"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="beta_lifetime_access",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            grandfather_claimed_beta_accounts,
            migrations.RunPython.noop,
        ),
    ]

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_beta_invites(apps, schema_editor):
    BetaInvite = apps.get_model("accounts", "BetaInvite")

    BetaInvite.objects.using(schema_editor.connection.alias).bulk_create(
        [
            BetaInvite(slot=slot, token=uuid.uuid4())
            for slot in range(1, 51)
        ]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_grandfather_existing_emails"),
    ]

    operations = [
        migrations.CreateModel(
            name="BetaInvite",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("slot", models.PositiveSmallIntegerField(unique=True)),
                (
                    "token",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        unique=True,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "claimed_by",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="beta_invite",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["slot"]},
        ),
        migrations.AddConstraint(
            model_name="betainvite",
            constraint=models.CheckConstraint(
                condition=models.Q(slot__gte=1, slot__lte=50),
                name="beta_invite_slot_1_to_50",
            ),
        ),
        migrations.RunPython(
            create_beta_invites,
            migrations.RunPython.noop,
        ),
    ]
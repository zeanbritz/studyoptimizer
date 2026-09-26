import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """StudiGarden user."""

    pass


class BetaInvite(models.Model):
    slot = models.PositiveSmallIntegerField(unique=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)

    claimed_by = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="beta_invite",
        null=True,
        blank=True,
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["slot"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(slot__gte=1, slot__lte=50),
                name="beta_invite_slot_1_to_50",
            ),
        ]

    def __str__(self):
        return f"Beta invite {self.slot}"
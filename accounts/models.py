import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """StudiGarden user."""

    beta_lifetime_access = models.BooleanField(default=False)


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


class StudyMembership(models.Model):
    """Paid access for either a recurring month or a prepaid year."""

    class Plan(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        ACTIVE = "active", "Active"
        NON_RENEWING = "non_renewing", "Not renewing"
        PAST_DUE = "past_due", "Payment failed"
        EXPIRED = "expired", "Expired"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_membership",
    )
    plan = models.CharField(max_length=10, choices=Plan.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # These must only be updated after a payment is verified server-side.
    paid_until = models.DateTimeField(null=True, blank=True)
    grace_until = models.DateTimeField(null=True, blank=True)

    paystack_customer_code = models.CharField(max_length=100, blank=True)

    # Used for recurring monthly memberships. Yearly purchases leave it empty.
    paystack_subscription_code = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        unique=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.user_id}: "
            f"{self.get_plan_display()} "
            f"({self.get_status_display()})"
        )
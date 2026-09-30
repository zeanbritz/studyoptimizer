import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


def new_study_payment_reference():
    """Generate a unique reference using characters accepted by Paystack."""
    return f"SG-{uuid.uuid4().hex}"


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

    # Update these only after verifying payment server-side.
    paid_until = models.DateTimeField(null=True, blank=True)
    grace_until = models.DateTimeField(null=True, blank=True)

    paystack_customer_code = models.CharField(max_length=100, blank=True)

    # Monthly subscriptions use this; one-time yearly purchases leave it empty.
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


class StudyPayment(models.Model):
    """One checkout or subscription-renewal payment record."""

    class Mode(models.TextChoices):
        TEST = "test", "Test"
        LIVE = "live", "Live"

    class Source(models.TextChoices):
        CHECKOUT = "checkout", "Checkout"
        RENEWAL = "renewal", "Subscription renewal"

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PENDING = "pending", "Awaiting payment"
        SUCCEEDED = "succeeded", "Verified successful"
        FAILED = "failed", "Failed"
        ABANDONED = "abandoned", "Abandoned"
        REVERSED = "reversed", "Reversed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="study_payments",
    )
    reference = models.CharField(
        max_length=40,
        unique=True,
        default=new_study_payment_reference,
        editable=False,
    )
    plan = models.CharField(
        max_length=10,
        choices=StudyMembership.Plan.choices,
    )
    mode = models.CharField(max_length=4, choices=Mode.choices)
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.CHECKOUT,
    )

    # Store the expected amount at the time the payment is created.
    # R99 = 9900 cents; R999 = 99900 cents.
    expected_amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="ZAR")

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.CREATED,
    )
    paystack_transaction_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expected_amount_cents__gt=0),
                name="study_payment_positive_amount",
            ),
            models.UniqueConstraint(
                fields=["mode", "paystack_transaction_id"],
                condition=models.Q(paystack_transaction_id__isnull=False),
                name="study_payment_unique_transaction_per_mode",
            ),
        ]

    def __str__(self):
        return f"{self.reference} ({self.get_status_display()})"
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


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


class StudyTier(models.TextChoices):
    FREE = "free", "Free"
    GROW = "grow", "Grow"
    BLOOM = "bloom", "Bloom"


PAID_TIER_CHOICES = [
    choice for choice in StudyTier.choices if choice[0] != StudyTier.FREE
]


class StudyMembership(models.Model):
    """A paid tier and its billing period, including earlier prepaid years."""

    class PaymentMode(models.TextChoices):
        TEST = "test", "Test"
        LIVE = "live", "Live"

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
    # Keep earlier full-access memberships on Bloom. Checkout sets this explicitly.
    tier = models.CharField(
        max_length=10,
        choices=PAID_TIER_CHOICES,
        default=StudyTier.BLOOM,
    )
    plan = models.CharField(max_length=10, choices=Plan.choices)
    payment_mode = models.CharField(
        max_length=4, choices=PaymentMode.choices, default=PaymentMode.LIVE,
    )
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

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tier__in=[StudyTier.GROW, StudyTier.BLOOM]),
                name="study_membership_paid_tier",
            ),
        ]

    def __str__(self):
        return (
            f"{self.user_id}: "
            f"{self.get_tier_display()} / {self.get_plan_display()} "
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
        max_length=100,
        unique=True,
        default=new_study_payment_reference,
        editable=False,
    )
    tier = models.CharField(
        max_length=10,
        choices=PAID_TIER_CHOICES,
        default=StudyTier.BLOOM,
    )
    plan = models.CharField(
        max_length=10,
        choices=StudyMembership.Plan.choices,
    )
    # Snapshot the Paystack plan selected for this payment; legacy records are blank.
    paystack_plan_code = models.CharField(max_length=100, blank=True)
    checkout_email = models.EmailField(blank=True)
    authorization_url = models.URLField(max_length=500, blank=True)
    mode = models.CharField(max_length=4, choices=Mode.choices)
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.CHECKOUT,
    )

    # Store the expected amount at the time the payment is created.
    # Grow = 3500 cents; Bloom = 9000 cents. Never reprice historical payments.
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

    # Renewal invoice identity and absolute service period. Never add a month
    # merely because another webhook arrived for the same charge or invoice.
    paystack_invoice_code = models.CharField(max_length=100, null=True, blank=True)
    paystack_subscription_code = models.CharField(max_length=100, blank=True)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tier__in=[StudyTier.GROW, StudyTier.BLOOM]),
                name="study_payment_paid_tier",
            ),
            models.CheckConstraint(
                condition=models.Q(expected_amount_cents__gt=0),
                name="study_payment_positive_amount",
            ),
            models.UniqueConstraint(
                fields=["mode", "paystack_transaction_id"],
                condition=models.Q(paystack_transaction_id__isnull=False),
                name="study_payment_unique_transaction_per_mode",
            ),
            models.UniqueConstraint(
                fields=["mode", "paystack_invoice_code"],
                condition=models.Q(paystack_invoice_code__isnull=False),
                name="study_payment_unique_invoice_per_mode",
            ),
        ]

    def __str__(self):
        return f"{self.reference} ({self.get_status_display()})"


class StudyRefund(models.Model):
    """One self-service first-purchase guarantee per account, with a durable outbox."""

    class Status(models.TextChoices):
        REQUESTED = "requested", "Checking eligibility"
        APPROVED = "approved", "Approved automatically"
        SUBMITTING = "submitting", "Confirming refund submission"
        PROCESSING = "processing", "Paystack is processing the refund"
        COMPLETED = "completed", "Refund completed"
        INELIGIBLE = "ineligible", "Outside the automatic refund guarantee"
        ATTENTION = "attention", "Refund needs attention"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="study_refund")
    payment = models.OneToOneField(StudyPayment, on_delete=models.PROTECT, related_name="refund_request")
    mode = models.CharField(max_length=4, choices=StudyPayment.Mode.choices, default=StudyPayment.Mode.LIVE)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="ZAR")
    requested_at = models.DateTimeField(default=timezone.now, editable=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    paystack_refund_id = models.PositiveBigIntegerField(null=True, blank=True)
    cancelled_subscription_code = models.CharField(max_length=100, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_result = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["requested_at", "pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount_cents__gt=0), name="study_refund_positive_amount"),
            models.UniqueConstraint(fields=["mode", "paystack_refund_id"],
                condition=models.Q(paystack_refund_id__isnull=False), name="study_refund_provider_once"),
        ]

    def __str__(self):
        return f"Refund {self.pk}: {self.get_status_display()}"


class StudyMonthlyUsage(models.Model):
    """Successful PDF exports and processed pages for one calendar month."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="monthly_study_usage",
    )
    period_start = models.DateField()
    pdf_exports = models.PositiveIntegerField(default=0)
    summary_pages = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "period_start"], name="study_usage_user_month",
            ),
        ]


class PaystackWebhookReceipt(models.Model):
    """Signed, sanitized notification inbox; receipt alone never grants access."""

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "received", "Waiting for processing"
        PROCESSED = "processed", "Processed"
        RETRY = "retry", "Waiting to retry"
        IGNORED = "ignored", "Ignored safely"

    mode = models.CharField(max_length=4, choices=StudyPayment.Mode.choices)
    event_type = models.CharField(max_length=64)
    payload_sha256 = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_status = models.CharField(
        max_length=16, choices=ProcessingStatus.choices, default=ProcessingStatus.RECEIVED,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_result = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-received_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["mode", "payload_sha256"], name="paystack_webhook_payload_once",
            ),
        ]

    def __str__(self):
        return f"{self.mode}: {self.event_type} ({self.pk})"

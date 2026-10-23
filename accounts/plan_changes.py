"""Server-side plan-change quotes. Recording intent alone never grants access.

This foundation is deliberately not exposed through customer routes yet. The
checkout, subscription scheduling and refund outbox must be connected first.
"""

from dataclasses import dataclass
from datetime import datetime
import re

from allauth.account.models import EmailAddress
from django.conf import settings
from django.utils import timezone

from .access import has_permanent_free_access
from .models import StudyMembership, StudyTier
from .payment_service import CheckoutNotAllowed
from .paystack_client import live_billing_enabled, live_checkout_enabled
from .plans import STUDY_PLANS


OPEN_CHANGE_STATES = (
    "checkout", "queued", "submitting", "scheduled", "settling", "attention",
)
RANK = {StudyTier.FREE: 0, StudyTier.GROW: 1, StudyTier.BLOOM: 2}


def plan_changes_enabled():
    return bool(live_billing_enabled() and getattr(settings, "PAYSTACK_LIVE_PLAN_CHANGES_ENABLED", False))


@dataclass(frozen=True)
class PlanChangeQuote:
    kind: str
    from_tier: str
    to_tier: str
    effective_at: datetime
    amount_due_now_cents: int
    next_monthly_amount_cents: int
    refund_current_lower_payment: bool = False


def quote_plan_change(*, user, tier):
    """Ignore browser prices/dates; derive the policy from owned paid-through time.

    A refund flag is not refund approval: canonical transaction and subscription
    ownership, the funded billing period, and prior refunds still need verifying.
    """
    if not plan_changes_enabled():
        raise CheckoutNotAllowed("Plan changes are not available here yet.")
    if not user or not user.is_authenticated or not user.is_active or not user.pk:
        raise CheckoutNotAllowed("An active account is required.")
    if has_permanent_free_access(user):
        raise CheckoutNotAllowed("Your permanent free access does not need a subscription.")
    if not isinstance(tier, str) or tier not in RANK:
        raise CheckoutNotAllowed("Choose Free, Grow or Bloom.")
    member = StudyMembership.objects.filter(user_id=user.pk).first()
    if not member or member.payment_mode != "live" or member.plan != "monthly":
        raise CheckoutNotAllowed("A verified live monthly membership is required for a plan change.")
    if member.status not in {"active", "non_renewing", "past_due", "expired"}:
        raise CheckoutNotAllowed("Verify the current payment before changing this plan.")
    if member.tier not in {"grow", "bloom"} or not member.paid_until:
        raise CheckoutNotAllowed("This membership has no confirmed paid-through date.")
    if not re.fullmatch(r"CUS_[A-Za-z0-9]{1,96}", member.paystack_customer_code):
        raise CheckoutNotAllowed("Confirm the Paystack customer before changing this plan.")
    if member.paystack_subscription_code and not re.fullmatch(r"SUB_[A-Za-z0-9]{1,96}", member.paystack_subscription_code):
        raise CheckoutNotAllowed("Confirm the subscription before changing this plan.")

    now = timezone.now()
    funded = member.status != "expired" and member.paid_until > now
    amount = STUDY_PLANS[tier].monthly_amount_cents
    if tier == StudyTier.FREE:
        return PlanChangeQuote("downgrade", member.tier, tier, member.paid_until if funded else now, 0, 0)

    if not live_checkout_enabled():
        raise CheckoutNotAllowed("New paid billing is paused. You can still stop renewals.")
    if not user.email or not EmailAddress.objects.filter(user=user, email__iexact=user.email, verified=True).exists():
        raise CheckoutNotAllowed("Verify your email address before authorising paid billing.")
    if not funded:
        # Grace access is not a funded new month. Do not refund a past period or
        # schedule a debit in the past merely because the status is past_due.
        return PlanChangeQuote("restart", member.tier, tier, now, amount, amount)
    if member.tier == tier:
        if member.status == "non_renewing":
            return PlanChangeQuote("resume", member.tier, tier, member.paid_until, 0, amount)
        raise CheckoutNotAllowed("You are already on this plan.")
    if RANK[tier] < RANK[member.tier]:
        return PlanChangeQuote("downgrade", member.tier, tier, member.paid_until, 0, amount)
    if not getattr(settings, "PAYSTACK_LIVE_REFUNDS_ENABLED", False):
        raise CheckoutNotAllowed("Upgrade refunds are paused. Your current plan is unchanged.")
    return PlanChangeQuote("upgrade", member.tier, tier, now, amount, amount, True)

"""Read-only customer controls. Rendering never contacts the payment provider."""

from django.urls import reverse
from django.utils import timezone

from .access import has_permanent_free_access
from .models import StudyMembership, StudyPlanChange, StudyRefund
from .payment_service import CheckoutNotAllowed
from .paystack_client import live_billing_enabled, live_checkout_enabled
from .plan_changes import OPEN_CHANGE_STATES, plan_changes_enabled, quote_plan_change


def billing_here(request):
    return bool(request.is_secure() and request.get_host().lower() == "studigarden.com" and live_billing_enabled())


def can_keep_current(user, change):
    member = StudyMembership.objects.filter(user=user, payment_mode="live", plan="monthly").first()
    return bool(
        plan_changes_enabled() and live_checkout_enabled() and user.is_active
        and not has_permanent_free_access(user) and member
        and member.tier == change.from_tier and member.paid_until == change.from_paid_until
        and member.status in {"active", "non_renewing", "past_due"}
        and member.paid_until > timezone.now() and not change.cancelled_at
        and change.previous_payment.status == "succeeded" and not change.previous_payment.discarded_at
        and not change.previous_payment.refund_requests.exclude(status="ineligible").exists()
        and not (change.cancel_requested and not change.restore_current)
        and not StudyRefund.objects.filter(user=user, mode="live", reason="first_payment").exclude(
            status__in=("completed", "ineligible"),
        ).exists()
    )


def plan_controls_context(request):
    context = {"plan_actions": {}, "show_plan_management": False}
    if not billing_here(request) or not request.user.is_authenticated:
        return context
    user = request.user
    member = StudyMembership.objects.filter(user=user, payment_mode="live", plan="monthly").first()
    changes = StudyPlanChange.objects.filter(user=user).select_related("payment", "previous_payment")
    pending = changes.filter(state__in=OPEN_CHANGE_STATES).first()
    latest = pending or changes.first()
    refunds = StudyRefund.objects.filter(user=user, mode="live", reason__in=("upgrade", "retired_subscription")).select_related("payment")
    context.update({
        "show_plan_management": bool(member or latest),
        "plan_change_status": latest,
        "open_customer_plan_change": pending,
        "plan_switch_refunds": refunds[:10],
        "plan_switching_enabled": plan_changes_enabled(),
    })
    if pending and pending.kind == "downgrade":
        context["stop_scheduled_change_url"] = reverse("cancel_scheduled_plan", args=[pending.pk])
        if can_keep_current(user, pending) and not pending.cancel_requested:
            context["keep_current_plan_url"] = reverse("cancel_scheduled_plan", args=[pending.pk]) + "?action=keep"
    if not plan_changes_enabled() or not member or has_permanent_free_access(user):
        return context
    if StudyRefund.objects.filter(user=user, mode="live").exclude(status__in=("completed", "ineligible")).exists():
        context["plan_change_wait_for_refund"] = True
        return context
    if pending and not (pending.kind == "upgrade" and pending.state == "checkout" and not pending.cancel_requested):
        return context
    for tier in ("free", "grow", "bloom"):
        if pending and tier != "bloom":
            continue
        try:
            quote = quote_plan_change(user=user, tier=tier)
        except CheckoutNotAllowed:
            continue
        # These routes intentionally do not bypass the existing guards for an
        # expired paid account or silently enable a same-tier stopped subscription.
        if quote.kind not in {"upgrade", "downgrade"}:
            context["paid_restart_not_available"] = True
            continue
        context["plan_actions"][tier] = {
            "url": reverse("change_live_plan", args=[tier]),
            "label": ("Continue Bloom checkout" if pending else
                      "Upgrade to Bloom" if quote.kind == "upgrade" else
                      "Switch to Free at period end" if tier == "free" else "Switch to Grow at renewal"),
        }
    context["free_plan_change"] = context["plan_actions"].get("free")
    return context

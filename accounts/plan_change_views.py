"""Owned, expiring confirmations for plan changes; GET requests are read-only."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .downgrade_cancellation import request_schedule_cancellation
from .downgrade_service import request_live_downgrade
from .live_checkout_views import _require_live
from .models import StudyPayment, StudyPlanChange
from .payment_service import CheckoutNotAllowed
from .paystack_client import PaystackError
from .plan_changes import (
    OPEN_CHANGE_STATES, plan_changes_enabled, quote_plan_change, quote_snapshot, schedule_cancel_snapshot,
)
from .plan_controls import can_keep_current
from .plans import STUDY_PLANS
from .upgrade_service import prepare_live_upgrade


SALT = "studigarden.plan-confirmation.v1"


def _confirmation(request, snapshot):
    if request.POST.get("confirm_plan_change") != "yes":
        raise CheckoutNotAllowed("Confirm the displayed price, billing date and renewal choice before continuing.")
    try:
        saved = signing.loads(request.POST.get("quote_token", ""), salt=SALT, max_age=900)
    except signing.BadSignature:
        raise CheckoutNotAllowed("This confirmation expired or is invalid. Review the current plan details and try again.") from None
    if saved != snapshot:
        raise CheckoutNotAllowed("Your membership changed. Review the current plan details before confirming again.")
    return saved


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def change_live_plan(request, tier):
    _require_live(request)
    if not plan_changes_enabled():
        raise Http404
    try:
        quote = quote_plan_change(user=request.user, tier=tier)
        if quote.kind not in {"upgrade", "downgrade"}:
            raise CheckoutNotAllowed("Paid restart and same-plan resumption are not available here yet. Your current access is unchanged.")
        pending = StudyPlanChange.objects.filter(user=request.user, state__in=OPEN_CHANGE_STATES).first()
        if pending and not (quote.kind == "upgrade" and pending.kind == "upgrade" and pending.state == "checkout" and not pending.cancel_requested):
            raise CheckoutNotAllowed("A plan change is already being handled. Check its status in Profile first.")
        snapshot = quote_snapshot(request.user, quote)
        if request.method == "POST":
            saved = _confirmation(request, snapshot)
            if quote.kind == "upgrade":
                payment = prepare_live_upgrade(user=request.user, expected_quote=saved)
                if payment.status == StudyPayment.Status.SUCCEEDED:
                    messages.info(request, "The upgrade payment is already verified. Check its progress in Profile; no new checkout was opened.")
                else:
                    response = redirect(payment.authorization_url)
                    response["Referrer-Policy"] = "no-referrer"
                    return response
            else:
                request_live_downgrade(user=request.user, tier=tier, expected_quote=saved)
                messages.info(request, "Your plan-change request is saved. Profile will show when the renewal change is confirmed. Your already-paid access is unchanged.")
            return redirect("my_plan")
    except (CheckoutNotAllowed, PaystackError) as exc:
        # Do not publish internal validation codes, provider bodies or tokens.
        message = str(exc) if isinstance(exc, CheckoutNotAllowed) else "We could not safely confirm this change with Paystack. Check Profile before trying again; do not pay through another link."
        messages.error(request, message)
        return redirect("my_plan")
    return render(request, "accounts/confirm_plan_change.html", {
        "quote": quote, "from_plan": STUDY_PLANS[quote.from_tier], "to_plan": STUDY_PLANS[quote.to_tier],
        "quote_token": signing.dumps(snapshot, salt=SALT, compress=True),
    })


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def cancel_scheduled_plan(request, change_id):
    # Stopping previously accepted billing remains available when NEW sales or
    # plan switching is paused. Keeping paid renewals requires explicit consent.
    _require_live(request)
    change = get_object_or_404(StudyPlanChange, pk=change_id, user=request.user, kind="downgrade", state__in=OPEN_CHANGE_STATES)
    action = request.POST.get("action") if request.method == "POST" else request.GET.get("action", "stop")
    if action not in {"stop", "keep"}:
        raise Http404
    restore = action == "keep"
    try:
        if restore and not can_keep_current(request.user, change):
            raise CheckoutNotAllowed("Keeping the previous paid renewal is not available for this change. You can still stop future billing.")
        snapshot = schedule_cancel_snapshot(request.user, change, restore)
        if request.method == "POST":
            saved = _confirmation(request, snapshot)
            result = request_schedule_cancellation(
                user=request.user, change_id=change.pk, restore_current=restore, expected_snapshot=saved,
            )
            if result is None:
                raise CheckoutNotAllowed("This change has already taken effect. Review your current plan in Profile.")
            messages.info(request, "Your request is saved. We are confirming the billing changes with Paystack. Check Profile for the result; already-paid access is unchanged.")
            return redirect("my_plan")
    except (CheckoutNotAllowed, PaystackError) as exc:
        messages.error(request, str(exc) if isinstance(exc, CheckoutNotAllowed) else "The billing change is awaiting confirmation. Check Profile shortly.")
        return redirect("my_plan")
    return render(request, "accounts/confirm_plan_change.html", {
        "scheduled_change": change, "restore_current": restore, "action": action,
        "from_plan": STUDY_PLANS[change.from_tier], "to_plan": STUDY_PLANS[change.to_tier],
        "quote_token": signing.dumps(snapshot, salt=SALT, compress=True),
    })

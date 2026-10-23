"""Cancel a saved future billing instruction without erasing paid access."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .access import has_permanent_free_access
from .downgrade_service import ScheduleAttention, _checked_old, _recover_submission
from .models import StudyMembership, StudyPlanChange
from .payment_service import CheckoutNotAllowed
from .paystack_client import PaystackError, live_checkout_enabled
from .plan_changes import OPEN_CHANGE_STATES
from .subscription_service import RENEWING_STATUSES, STOPPED_STATUSES, _matches_subscription


def request_schedule_cancellation(*, user, change_id=None, restore_current=False, allow_inactive=False, received_at=None):
    if (not user or not user.is_authenticated or not user.pk
            or (not user.is_active and not allow_inactive) or type(restore_current) is not bool):
        raise CheckoutNotAllowed("An owned account and an explicit cancellation choice are required.")
    if restore_current and not live_checkout_enabled():
        raise CheckoutNotAllowed("Resuming paid renewals is currently paused.")
    with transaction.atomic():
        locked = get_user_model().objects.select_for_update().get(pk=user.pk)
        if not locked.is_active and not allow_inactive:
            raise CheckoutNotAllowed("An active account is required.")
        changes = StudyPlanChange.objects.select_for_update().filter(user=locked, kind="downgrade")
        if change_id is not None:
            change = changes.filter(pk=change_id).first()
            if change is None:
                raise CheckoutNotAllowed("That scheduled change does not belong to this account.")
        else:
            change = changes.filter(state__in=OPEN_CHANGE_STATES).first()
        if change is None or change.state == "applied":
            return None
        if change.cancelled_at:
            return change
        if change.cancel_requested and not change.restore_current and restore_current:
            raise CheckoutNotAllowed("Cancellation has already been accepted. Resume the current plan separately.")
        if restore_current:
            member = StudyMembership.objects.filter(user=locked, payment_mode="live").first()
            if (not locked.is_active or has_permanent_free_access(locked) or not member
                    or member.tier != change.from_tier or member.paid_until != change.from_paid_until
                    or member.paid_until <= timezone.now()):
                raise CheckoutNotAllowed("The previous paid month cannot be resumed by this scheduled-change control.")
        change.cancel_requested = True
        change.cancel_requested_at = change.cancel_requested_at or received_at or timezone.now()
        change.restore_current = restore_current
        if change.state == "attention":
            change.state = "scheduled" if change.to_subscription_code else (
                "submitting" if change.subscription_posted_at else "queued"
            )
        change.next_attempt_at, change.last_result = None, "schedule_cancel_requested"
        change.save(update_fields=[
            "cancel_requested", "cancel_requested_at", "restore_current", "state", "next_attempt_at", "last_result", "updated_at",
        ])
        return change


def checked_change_subscription(client, change, code):
    plan = change.from_plan_code if code == change.from_subscription_code else change.to_plan_code
    if code not in (change.from_subscription_code, change.to_subscription_code) or not code or not plan:
        raise ScheduleAttention("cancellation_subscription_not_owned")
    value = client.fetch_subscription(code)
    if (value.get("subscription_code") != code
            or not _matches_subscription(value, change.customer_code, plan, "live")):
        raise ScheduleAttention("cancellation_subscription_scope_mismatch")
    if StudyMembership.objects.filter(paystack_subscription_code=code).exclude(user_id=change.user_id).exists():
        raise ScheduleAttention("cancellation_subscription_owned_elsewhere")
    return value


def stop_change_subscription(client, change, code):
    value = checked_change_subscription(client, change, code)
    if value.get("status") not in STOPPED_STATUSES:
        token = value.get("email_token")
        if (value.get("status") not in RENEWING_STATUSES or not isinstance(token, str)
                or not 1 <= len(token) <= 500 or any(c in token for c in "\r\n")):
            raise ScheduleAttention("cancellation_token_unconfirmed")
        try:
            client.disable_subscription(code, token)
        except PaystackError:
            pass
        if checked_change_subscription(client, change, code).get("status") not in STOPPED_STATUSES:
            raise PaystackError("Future billing cancellation is awaiting provider confirmation.")
    return code


def _resume_old(client, change, member, user):
    if (not user.is_active or has_permanent_free_access(user) or member.tier != change.from_tier
            or member.paystack_subscription_code not in (None, "", change.from_subscription_code)
            or member.paid_until != change.from_paid_until or member.paid_until <= timezone.now()):
        raise ScheduleAttention("previous_plan_cannot_resume")
    value = _checked_old(client, change)
    try:
        debit = parse_datetime(value.get("next_payment_date", ""))
    except (TypeError, ValueError):
        debit = None
    if (not debit or timezone.is_naive(debit) or debit <= timezone.now() + timedelta(seconds=30)
            or abs(debit - change.from_paid_until) > timedelta(minutes=5)):
        raise ScheduleAttention("resume_next_debit_unconfirmed")
    if value.get("status") not in RENEWING_STATUSES:
        token = value.get("email_token")
        if (value.get("status") not in STOPPED_STATUSES or not isinstance(token, str)
                or not 1 <= len(token) <= 500 or any(c in token for c in "\r\n")):
            raise ScheduleAttention("resume_token_unconfirmed")
        try:
            client.enable_subscription(change.from_subscription_code, token)
        except PaystackError:
            pass
        if checked_change_subscription(client, change, change.from_subscription_code).get("status") not in RENEWING_STATUSES:
            raise PaystackError("Resuming the previous renewal is awaiting confirmation.")
    member.status, member.grace_until, member.paystack_subscription_code = "active", None, change.from_subscription_code
    member.save(update_fields=["status", "grace_until", "paystack_subscription_code", "updated_at"])


def cancel_scheduled_change(client, change):
    """Called with the user/change lock. An uncertain create is GET-reconciled first."""
    user = get_user_model().objects.select_for_update().get(pk=change.user_id)
    member = StudyMembership.objects.select_for_update().get(user_id=change.user_id)
    if change.cancelled_at:
        return change
    if (member.payment_mode != "live" or member.paystack_customer_code != change.customer_code
            or change.previous_payment.user_id != change.user_id or change.previous_payment.mode != "live"):
        raise ScheduleAttention("schedule_cancellation_scope_changed")
    if change.subscription_posted_at and not change.to_subscription_code:
        change = _recover_submission(client, change, allow_stopped=True)
    if change.to_subscription_code:
        stop_change_subscription(client, change, change.to_subscription_code)
    # Stop both potential renewals before reporting cancellation. Resumption is
    # explicit and only possible while the already-paid higher month remains.
    if change.restore_current:
        _resume_old(client, change, member, user)
    else:
        stop_change_subscription(client, change, change.from_subscription_code)
        if member.paystack_subscription_code in (change.from_subscription_code, change.to_subscription_code):
            member.status, member.grace_until = "non_renewing", None
            member.save(update_fields=["status", "grace_until", "updated_at"])
    change.state, change.cancelled_at, change.next_attempt_at = "cancelled", timezone.now(), None
    change.last_result = "previous_plan_resumed" if change.restore_current else "scheduled_renewals_stopped"
    change.save(update_fields=["state", "cancelled_at", "next_attempt_at", "last_result", "updated_at"])
    return change

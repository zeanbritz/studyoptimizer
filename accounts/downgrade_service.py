"""Durable future-dated downgrade scheduling; not exposed to customers yet.

An accepted request stops the old renewal but preserves paid access. A paid
lower tier is NOT granted by creating a subscription or by its metadata. The
verified first-debit and customer-control paths are connected in a later step.
"""

import hashlib
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .access import has_permanent_free_access
from .models import StudyMembership, StudyPayment, StudyPlanChange, StudyRefund
from .payment_service import CheckoutNotAllowed
from .paystack_checkout import _validate_plan, _validate_transaction
from .paystack_client import PaystackError, PaystackLiveClient, live_billing_enabled
from .plan_changes import OPEN_CHANGE_STATES, quote_plan_change, validate_quote_snapshot
from .subscription_service import (
    RENEWING_STATUSES, STOPPED_STATUSES, _find_subscription, _matches_subscription,
)
from .upgrade_service import _period


class ScheduleAttention(PaystackError):
    """Internal constant only; do not save provider bodies, card tokens or PII."""


def _fingerprint(code):
    if not isinstance(code, str) or not re.fullmatch(r"AUTH_[A-Za-z0-9]{1,195}", code):
        raise ScheduleAttention("card_authorization_unconfirmed")
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def _card(result):
    authorization = result.get("authorization")
    if (not isinstance(authorization, dict) or authorization.get("reusable") is not True
            or authorization.get("channel") != "card"):
        raise ScheduleAttention("reusable_card_required")
    code = authorization.get("authorization_code")
    _fingerprint(code)
    return code


def _pending_refund(user_id):
    return StudyRefund.objects.filter(user_id=user_id, mode="live").exclude(
        status__in=("completed", "ineligible"),
    ).exists()


def _funding_payment(member):
    from .membership_proof import membership_payment
    initial = membership_payment(member)
    if not initial:
        raise CheckoutNotAllowed("Verify the current subscription payment before changing its renewal.")
    funding = StudyPayment.objects.filter(
        user_id=member.user_id, mode="live", tier=member.tier, plan="monthly", status="succeeded",
        period_end=member.paid_until, paystack_plan_code=initial.paystack_plan_code,
        verified_at__isnull=False, paystack_transaction_id__isnull=False, discarded_at__isnull=True,
    ).first() or initial
    return initial, funding


def _verify_funding(client, payment, customer_code):
    result = client.verify(payment.reference)
    paid_at = _validate_transaction(result, payment)
    if (payment.mode != "live" or payment.status != "succeeded" or not payment.verified_at
            or result.get("status") != "success" or not paid_at
            or result.get("id") != payment.paystack_transaction_id
            or result["customer"]["customer_code"] != customer_code):
        raise ScheduleAttention("funding_payment_unconfirmed")
    return result, _period(payment, paid_at)


def _validate_lower_plan(client, change):
    # Reuse checkout's provider price validation without creating a payment.
    expected = StudyPayment(
        mode="live", tier=change.to_tier, plan="monthly", paystack_plan_code=change.to_plan_code,
        expected_amount_cents=change.monthly_amount_cents, currency=change.currency,
    )
    _validate_plan(client.fetch_plan(change.to_plan_code), expected)


def request_live_downgrade(*, user, tier, expected_quote=None):
    """Record an owned, zero-charge instruction; provider mutations belong to the worker."""
    quote = quote_plan_change(user=user, tier=tier)
    if quote.kind != "downgrade":
        raise CheckoutNotAllowed("Choose a lower plan for your next renewal.")
    client = PaystackLiveClient()
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        quote = quote_plan_change(user=user, tier=tier)
        validate_quote_snapshot(user, quote, expected_quote)
        if quote.kind != "downgrade" or _pending_refund(user.pk):
            raise CheckoutNotAllowed("Finish the existing payment or refund before scheduling a change.")
        existing = StudyPlanChange.objects.filter(user=user, state__in=OPEN_CHANGE_STATES).first()
        if existing:
            if existing.kind == "downgrade" and existing.to_tier == tier and not existing.cancel_requested:
                return existing
            raise CheckoutNotAllowed("A plan change is already being handled. Check its status first.")
        member = StudyMembership.objects.select_for_update().get(user=user, payment_mode="live", plan="monthly")
        initial, funding = _funding_payment(member)
        subscription = _find_subscription(client, member, initial)
        code = subscription["subscription_code"]
        if subscription.get("status") not in RENEWING_STATUSES | STOPPED_STATUSES:
            raise ScheduleAttention("previous_subscription_state_unconfirmed")
        if (StudyMembership.objects.filter(paystack_subscription_code=code).exclude(pk=member.pk).exists()
                or funding.paystack_subscription_code not in ("", code)
                or (funding.source == "renewal" and funding.paystack_subscription_code != code)):
            raise ScheduleAttention("funded_subscription_mismatch")
        result, (start, end) = _verify_funding(client, funding, member.paystack_customer_code)
        if end != member.paid_until or funding.refund_requests.exclude(status="ineligible").exists():
            raise CheckoutNotAllowed("The current paid billing period must be confirmed before changing renewal.")
        fingerprint = ""
        if tier != "free":
            # The exact card already charged for this period, not the customer's
            # most recent unrelated authorisation selected implicitly by Paystack.
            authorization = _card(result)
            if _card(subscription) != authorization or not start <= timezone.now() < end:
                raise ScheduleAttention("current_card_or_billing_period_changed")
            fingerprint = _fingerprint(authorization)
        funding.period_start, funding.period_end, funding.paystack_subscription_code = start, end, code
        funding.save(update_fields=["period_start", "period_end", "paystack_subscription_code", "updated_at"])
        change = StudyPlanChange(
            user=user, kind="downgrade", state="queued", from_tier=member.tier, to_tier=tier,
            from_subscription_code=code, from_plan_code=initial.paystack_plan_code,
            to_plan_code="" if tier == "free" else _live_plan_code(tier),
            amount_due_now_cents=0, monthly_amount_cents=quote.next_monthly_amount_cents,
            customer_code=member.paystack_customer_code, billing_email=funding.checkout_email,
            from_paid_until=end, effective_at=quote.effective_at, previous_payment=funding,
            authorization_fingerprint=fingerprint,
        )
        if tier != "free":
            _validate_lower_plan(client, change)
        change.save()
        return change


def _live_plan_code(tier):
    from django.conf import settings
    code = settings.PAYSTACK_LIVE_PLAN_CODES.get(tier)
    if not isinstance(code, str) or not re.fullmatch(r"PLN_[A-Za-z0-9]{1,96}", code):
        raise CheckoutNotAllowed("The lower monthly plan is not configured.")
    return code


def _scope(change, member):
    previous = change.previous_payment
    if not (change.kind == "downgrade" and previous.user_id == member.user_id == change.user_id
            and member.payment_mode == previous.mode == "live" and member.plan == previous.plan == "monthly"
            and member.tier == previous.tier == change.from_tier
            and member.paystack_customer_code == change.customer_code
            and member.paystack_subscription_code in (None, "", change.from_subscription_code)
            and previous.paystack_subscription_code == change.from_subscription_code
            and previous.paystack_plan_code == change.from_plan_code
            and previous.status == "succeeded" and previous.verified_at and previous.paystack_transaction_id
            and not previous.discarded_at and change.amount_due_now_cents == 0
            and change.currency == previous.currency == "ZAR" and member.paid_until == change.from_paid_until
            and previous.period_end == change.from_paid_until
            and change.effective_at >= change.from_paid_until
            and (change.to_tier == "free" or change.effective_at == change.from_paid_until)
            and ((change.to_tier == "free" and change.monthly_amount_cents == 0 and not change.to_plan_code)
                 or (change.from_tier == "bloom" and change.to_tier == "grow"
                     and change.monthly_amount_cents > 0 and change.to_plan_code))):
        raise ScheduleAttention("downgrade_scope_changed")
    if StudyMembership.objects.filter(paystack_subscription_code=change.from_subscription_code).exclude(pk=member.pk).exists():
        raise ScheduleAttention("previous_subscription_owned_elsewhere")


def _checked_old(client, change):
    subscription = client.fetch_subscription(change.from_subscription_code)
    if (subscription.get("subscription_code") != change.from_subscription_code
            or not _matches_subscription(subscription, change.customer_code, change.from_plan_code, "live")):
        raise ScheduleAttention("previous_subscription_owner_mismatch")
    return subscription


def _stop_old(client, change):
    subscription = _checked_old(client, change)
    if subscription.get("status") not in STOPPED_STATUSES:
        token = subscription.get("email_token")
        if (subscription.get("status") not in RENEWING_STATUSES or not isinstance(token, str)
                or not 1 <= len(token) <= 500 or any(c in token for c in "\r\n")):
            raise ScheduleAttention("previous_cancellation_details_unconfirmed")
        try:
            client.disable_subscription(change.from_subscription_code, token)
        except PaystackError:
            pass  # A timeout may follow success; GET the exact remote object.
        if _checked_old(client, change).get("status") not in STOPPED_STATUSES:
            raise PaystackError("The previous renewal cancellation is still being confirmed.")


def _listed_subscriptions(client, change):
    customer = client.fetch_customer(change.customer_code)
    if (customer.get("domain") != "live" or customer.get("customer_code") != change.customer_code
            or type(customer.get("id")) is not int or customer["id"] <= 0):
        raise ScheduleAttention("scheduled_customer_unconfirmed")
    listed = client.list_customer_subscriptions(customer["id"])
    if len(listed) >= 100:
        raise ScheduleAttention("subscription_list_incomplete")
    if any(not isinstance(item, dict) or not isinstance(item.get("subscription_code"), str)
           or not re.fullmatch(r"SUB_[A-Za-z0-9]{1,96}", item["subscription_code"]) for item in listed):
        raise ScheduleAttention("subscription_list_invalid")
    return listed


def _matches_new(subscription, change):
    if not _matches_subscription(subscription, change.customer_code, change.to_plan_code, "live"):
        return False
    plan, authorization = subscription["plan"], subscription.get("authorization")
    created = subscription.get("createdAt") or subscription.get("created_at")
    try:
        created = parse_datetime(created) if isinstance(created, str) else None
        fingerprint = _fingerprint(authorization.get("authorization_code")) if isinstance(authorization, dict) else ""
    except (TypeError, ValueError):
        return False
    return bool(
        created and timezone.is_aware(created) and change.subscription_posted_at
        and change.subscription_posted_at - timedelta(minutes=5) <= created <= timezone.now() + timedelta(minutes=5)
        and subscription["subscription_code"] not in change.subscription_baseline
        and type(subscription.get("start")) is int
        and subscription["start"] == int(change.effective_at.timestamp())
        and type(subscription.get("amount")) is int and subscription["amount"] == change.monthly_amount_cents
        and type(plan.get("amount")) is int and plan["amount"] == change.monthly_amount_cents
        and plan.get("currency") == "ZAR" and plan.get("interval") == "monthly"
        and fingerprint == change.authorization_fingerprint
        and subscription.get("status") in RENEWING_STATUSES | STOPPED_STATUSES
    )


def _attach_new(client, change, code, *, allow_stopped=False):
    subscription = client.fetch_subscription(code)
    if subscription.get("subscription_code") != code or not _matches_new(subscription, change):
        raise ScheduleAttention("scheduled_subscription_proof_mismatch")
    if StudyMembership.objects.filter(paystack_subscription_code=code).exists():
        raise ScheduleAttention("scheduled_subscription_is_current")
    if StudyPlanChange.objects.filter(to_subscription_code=code).exclude(pk=change.pk).exists():
        raise ScheduleAttention("scheduled_subscription_owned_elsewhere")
    if subscription.get("status") in STOPPED_STATUSES and not allow_stopped:
        raise ScheduleAttention("lower_subscription_already_stopped")
    change.to_subscription_code = code
    change.state, change.last_result = "scheduled", "lower_renewal_scheduled"
    change.next_attempt_at = change.effective_at
    change.save(update_fields=["to_subscription_code", "state", "last_result", "next_attempt_at", "updated_at"])
    return change


def _recover_submission(client, change, *, allow_stopped=False):
    matches = []
    for item in _listed_subscriptions(client, change):
        code = item["subscription_code"]
        if code in change.subscription_baseline:
            continue
        # Canonical GET, not list ordering or an untrusted query filter.
        if _matches_subscription(item, change.customer_code, change.to_plan_code, "live"):
            canonical = client.fetch_subscription(code)
            if canonical.get("subscription_code") != code:
                raise ScheduleAttention("scheduled_subscription_identity_changed")
            if _matches_new(canonical, change):
                matches.append(code)
    if len(set(matches)) > 1:
        raise ScheduleAttention("scheduled_subscription_ambiguous")
    if not matches:
        raise PaystackError("The subscription submission is awaiting confirmation. Do not submit another.")
    return _attach_new(client, change, matches[0], allow_stopped=allow_stopped)


def _defer(change, code, *, attention=False):
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=change.user_id)
        current = StudyPlanChange.objects.select_for_update().get(pk=change.pk)
        if current.state != change.state or current.state not in {"queued", "submitting", "scheduled", "settling"}:
            return current
        current.state = "attention" if attention else current.state
        current.attempt_count = min(current.attempt_count + 1, 2_147_483_647)
        current.last_result = code
        current.next_attempt_at = timezone.now() + timedelta(seconds=min(60 * 2 ** min(current.attempt_count - 1, 6), 3600))
        current.save(update_fields=["state", "attempt_count", "last_result", "next_attempt_at", "updated_at"])
        return current


def process_downgrade_change(change_id):
    client = PaystackLiveClient()
    change = StudyPlanChange.objects.select_related("previous_payment").get(pk=change_id, kind="downgrade")
    if (change.state not in {"queued", "submitting", "scheduled", "settling"}
            or (change.next_attempt_at and change.next_attempt_at > timezone.now())):
        return change
    attempted_state = change.state
    try:
        authorization = None
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=change.user_id)
            change = StudyPlanChange.objects.select_for_update().select_related("previous_payment").get(pk=change.pk)
            if (change.state not in {"queued", "submitting", "scheduled", "settling"}
                    or (change.next_attempt_at and change.next_attempt_at > timezone.now())):
                return change
            member = StudyMembership.objects.select_for_update().get(user=user)
            first_refund = StudyRefund.objects.filter(user=user, mode="live", reason="first_payment").exclude(
                status__in=("completed", "ineligible"),
            ).first()
            if first_refund and (first_refund.status == "requested" or (
                    first_refund.status == "attention" and not first_refund.approved_at)):
                return _defer(change, "refund_eligibility_pending")
            guarantee = bool(first_refund)
            if (change.cancel_requested or guarantee or not user.is_active or has_permanent_free_access(user)
                    or change.previous_payment.status == "reversed"):
                from .downgrade_cancellation import cancel_scheduled_change
                change.cancel_requested = True
                change.cancel_requested_at = change.cancel_requested_at or timezone.now()
                if guarantee or not user.is_active or has_permanent_free_access(user):
                    change.restore_current = False
                change.save(update_fields=["cancel_requested", "cancel_requested_at", "restore_current", "updated_at"])
                return cancel_scheduled_change(client, change)
            _scope(change, member)
            if change.state == "submitting":
                # Even when its desired date has passed, GET-reconcile an
                # uncertain submission. Never retry the create POST blindly.
                return _recover_submission(client, change)
            if change.state == "scheduled":
                if change.to_tier == "free":
                    change.state, change.last_result = "applied", "free_plan_effective"
                    change.applied_at, change.next_attempt_at = timezone.now(), None
                else:
                    # No entitlement is granted merely by waiting until a date.
                    # A verified paid invoice must fund the lower paid tier.
                    change.last_result = "awaiting_verified_lower_payment"
                    change.next_attempt_at = timezone.now() + timedelta(minutes=5)
                change.save(update_fields=["state", "last_result", "applied_at", "next_attempt_at", "updated_at"])
                return change
            if change.to_tier != "free":
                if change.effective_at <= timezone.now():
                    raise ScheduleAttention("lower_start_date_passed")
                _validate_lower_plan(client, change)
                result, (_, end) = _verify_funding(client, change.previous_payment, change.customer_code)
                authorization = _card(result)
                if (_fingerprint(authorization) != change.authorization_fingerprint
                        or _card(_checked_old(client, change)) != authorization or end != change.from_paid_until):
                    raise ScheduleAttention("scheduled_card_or_period_changed")
                listed = _listed_subscriptions(client, change)
                if any(_matches_subscription(item, change.customer_code, change.to_plan_code, "live")
                       and item.get("status") in RENEWING_STATUSES for item in listed):
                    raise ScheduleAttention("lower_subscription_already_exists")
            _stop_old(client, change)
            member.status, member.grace_until = "non_renewing", None
            member.paystack_subscription_code = change.from_subscription_code
            member.save(update_fields=["status", "grace_until", "paystack_subscription_code", "updated_at"])
            change.old_stopped_at = timezone.now()
            if change.to_tier == "free":
                change.state = "scheduled" if change.effective_at > timezone.now() else "applied"
                change.last_result = "free_renewal_scheduled" if change.state == "scheduled" else "free_plan_effective"
                change.next_attempt_at = change.effective_at if change.state == "scheduled" else None
                change.applied_at = timezone.now() if change.state == "applied" else None
                change.save()
                return change
            change.subscription_baseline = sorted({item["subscription_code"] for item in listed})
            if change.effective_at <= timezone.now():
                raise ScheduleAttention("lower_start_date_passed")
            change.subscription_posted_at = timezone.now()
            change.state, change.last_result = "submitting", "lower_subscription_submission_started"
            change.next_attempt_at = timezone.now() + timedelta(minutes=1)
            change.save()
        # Submission intent has committed. Lock against another worker while
        # POSTing, but a DB rollback cannot erase that earlier durable intent.
        attempted_state = change.state
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=change.user_id)
            change = StudyPlanChange.objects.select_for_update().select_related("previous_payment").get(pk=change.pk)
            if change.state != "submitting" or change.cancel_requested:
                return change
            _scope(change, StudyMembership.objects.select_for_update().get(user_id=change.user_id))
            if (change.effective_at <= timezone.now() or _pending_refund(change.user_id)
                    or not user.is_active or has_permanent_free_access(user)):
                raise ScheduleAttention("lower_submission_scope_changed")
            result = client.create_subscription(
                customer_code=change.customer_code, plan_code=change.to_plan_code,
                authorization_code=authorization, start_date=change.effective_at,
            )
            code = result.get("subscription_code")
            if not isinstance(code, str) or not re.fullmatch(r"SUB_[A-Za-z0-9]{1,96}", code):
                raise PaystackError("The subscription response needs confirmation before continuing.")
            return _attach_new(client, change, code)
    except ScheduleAttention as exc:
        change.state = attempted_state
        return _defer(change, str(exc), attention=True)
    except PaystackError:
        change.state = attempted_state
        since = change.subscription_posted_at or change.requested_at
        if since < timezone.now() - timedelta(hours=24):
            return _defer(change, "lower_subscription_needs_attention", attention=True)
        return _defer(change, "lower_provider_confirmation_pending")
    except IntegrityError:
        change.state = attempted_state
        return _defer(change, "lower_subscription_identity_conflict", attention=True)


def process_downgrade_batch(limit=5):
    if not live_billing_enabled():
        raise PaystackError("Live billing is disabled.")
    due = StudyPlanChange.objects.filter(kind="downgrade", state__in=("queued", "submitting", "scheduled", "settling")).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()),
    ).order_by("requested_at", "pk").values_list("pk", flat=True)[:limit]
    outcomes = []
    for pk in list(due):
        try:
            change = process_downgrade_change(pk)
        except DatabaseError:
            raise
        except Exception:
            change = _defer(StudyPlanChange.objects.get(pk=pk), "lower_processor_error", attention=True)
        outcomes.append((change.pk, change.state, change.last_result))
    return outcomes

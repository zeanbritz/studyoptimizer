"""Verified upgrade settlement behind the separate live plan-change gate.

The old membership survives an unpaid checkout. Only a canonical new payment can
activate Bloom; the worker then stops the exact old subscription and queues its
current-period credit in the existing durable refund outbox.
"""

from datetime import timedelta
import re

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .access import has_permanent_free_access
from .models import StudyMembership, StudyPayment, StudyPlanChange, StudyRefund
from .payment_service import CheckoutNotAllowed, create_checkout_attempt
from .paystack_client import (
    PaystackError, PaystackLiveClient, live_billing_enabled, live_callback_url, valid_authorization_url,
)
from .plan_changes import OPEN_CHANGE_STATES, quote_plan_change, validate_quote_snapshot
from .subscription_service import (
    RENEWING_STATUSES, STOPPED_STATUSES, _find_subscription, _matches_subscription,
)


class UpgradeAttention(PaystackError):
    """Internal constant outcome only; never copy provider bodies or tokens."""


def _pending_guarantee(user_id):
    return StudyRefund.objects.filter(user_id=user_id, mode="live", reason="first_payment").exclude(
        status__in=("completed", "ineligible"),
    ).exists()


def _initial_payment(member):
    # The future scheduled-downgrade path must provide equivalent explicit
    # payment/subscription proof before a renewed Grow plan can upgrade again.
    from .membership_proof import membership_payment
    payment = membership_payment(member)
    if not payment:
        raise CheckoutNotAllowed("The current subscription payment must be verified first.")
    return payment


def _period(payment, paid_at):
    from .paystack_checkout import _one_month_after

    if payment.source == "checkout":
        start, end = paid_at, _one_month_after(paid_at)
        if payment.period_start not in (None, start) or payment.period_end not in (None, end):
            raise UpgradeAttention("funded_period_mismatch")
    elif payment.source == "renewal":
        start, end = payment.period_start, payment.period_end
        if (not start or not end or not timedelta(days=27) <= end - start <= timedelta(days=32)
                or not start - timedelta(minutes=5) <= paid_at <= end + timedelta(minutes=5)):
            raise UpgradeAttention("funded_period_invalid")
    else:
        raise UpgradeAttention("funded_payment_source_invalid")
    return start, end


def _verify_lower_payment(client, payment, customer_code):
    from .paystack_checkout import _validate_transaction

    if not (payment.mode == "live" and payment.tier == "grow" and payment.plan == "monthly"
            and payment.status == "succeeded" and payment.verified_at and payment.paystack_transaction_id):
        raise UpgradeAttention("lower_payment_not_verified")
    result = client.verify(payment.reference)
    paid_at = _validate_transaction(result, payment)
    if (result.get("status") != "success" or result.get("id") != payment.paystack_transaction_id
            or result["customer"]["customer_code"] != customer_code or not paid_at):
        raise UpgradeAttention("lower_payment_owner_mismatch")
    start, end = _period(payment, paid_at)
    return result, start, end


def prepare_live_upgrade(*, user, replace_reference=None, expected_quote=None):
    """The target/price/refund policy are never taken from form data."""
    from .paystack_checkout import _record_checkout_result, _validate_plan, _validate_transaction

    quote = quote_plan_change(user=user, tier="bloom")
    if quote.kind != "upgrade":
        raise CheckoutNotAllowed("This account does not have a funded Grow month to upgrade.")
    client = PaystackLiveClient()
    # Commit the payment and consent record before /transaction/initialize.
    # Provider-unique references survive a timeout instead of opening another charge.
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        quote = quote_plan_change(user=user, tier="bloom")
        validate_quote_snapshot(user, quote, expected_quote)
        if quote.kind != "upgrade" or _pending_guarantee(user.pk):
            raise CheckoutNotAllowed("Finish the current refund or payment before upgrading.")
        change = StudyPlanChange.objects.select_for_update().filter(user=user, state__in=OPEN_CHANGE_STATES).first()
        if change:
            if change.kind != "upgrade" or change.state != "checkout" or change.cancel_requested:
                raise CheckoutNotAllowed("A plan change is already being processed. Check its status before starting another.")
            payment = StudyPayment.objects.select_for_update().get(pk=change.payment_id)
            if replace_reference == payment.reference:
                result = client.verify(payment.reference)
                _validate_transaction(result, payment)
                if result["status"] in {"processing", "ongoing", "queued"}:
                    raise CheckoutNotAllowed("Paystack is still processing this upgrade. Check its status shortly.")
                payment = _record_checkout_result(user, payment, result, "live")
                if payment.status == "succeeded":
                    return payment
                payment.discarded_at = timezone.now()
                payment.save(update_fields=["discarded_at", "updated_at"])
                payment = create_checkout_attempt(user=user, tier="bloom", mode="live")
                change.payment = payment
                change.save(update_fields=["payment", "updated_at"])
        else:
            member = StudyMembership.objects.select_for_update().get(user=user, payment_mode="live", plan="monthly", tier="grow")
            initial = _initial_payment(member)
            subscription = _find_subscription(client, member, initial)
            if subscription.get("status") not in RENEWING_STATUSES | STOPPED_STATUSES:
                raise PaystackError("The current subscription state could not be verified.")
            funding = StudyPayment.objects.filter(
                user=user, mode="live", tier="grow", plan="monthly", status="succeeded",
                paystack_plan_code=initial.paystack_plan_code, period_end=member.paid_until,
                verified_at__isnull=False, paystack_transaction_id__isnull=False, discarded_at__isnull=True,
            ).first() or initial
            if (funding.paystack_subscription_code and
                    funding.paystack_subscription_code != subscription["subscription_code"]):
                raise UpgradeAttention("funded_subscription_mismatch")
            if funding.source == "renewal" and not funding.paystack_subscription_code:
                raise UpgradeAttention("funded_subscription_missing")
            _, start, end = _verify_lower_payment(client, funding, member.paystack_customer_code)
            if not start <= timezone.now() < end or end != member.paid_until:
                raise CheckoutNotAllowed("The current paid billing period is still being verified. Try again shortly.")
            if funding.refund_requests.exclude(status="ineligible").exists():
                raise CheckoutNotAllowed("A refund for this billing period is already being handled.")
            # Enrich legacy first-checkout records with canonical service dates.
            # This records proof, not a new entitlement or a changed price.
            funding.period_start, funding.period_end = start, end
            funding.paystack_subscription_code = subscription["subscription_code"]
            funding.save(update_fields=["period_start", "period_end", "paystack_subscription_code", "updated_at"])
            payment = create_checkout_attempt(user=user, tier="bloom", mode="live")
            change = StudyPlanChange.objects.create(
                user=user, kind="upgrade", state="checkout", from_tier="grow", to_tier="bloom",
                from_subscription_code=subscription["subscription_code"], from_plan_code=initial.paystack_plan_code,
                to_plan_code=payment.paystack_plan_code, amount_due_now_cents=payment.expected_amount_cents,
                monthly_amount_cents=payment.expected_amount_cents, customer_code=member.paystack_customer_code,
                billing_email=funding.checkout_email, from_paid_until=end, effective_at=quote.effective_at,
                payment=payment, previous_payment=funding,
            )
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        quote_plan_change(user=user, tier="bloom")
        change = StudyPlanChange.objects.select_for_update().get(pk=change.pk)
        payment = StudyPayment.objects.select_for_update().get(pk=payment.pk)
        if change.state != "checkout" or change.cancel_requested or change.payment_id != payment.pk or payment.discarded_at:
            raise CheckoutNotAllowed("This upgrade changed in another tab. Refresh your Profile.")
        if valid_authorization_url(payment.authorization_url) and payment.status in {"pending", "failed", "abandoned"}:
            return payment
        if payment.status != "created":
            raise CheckoutNotAllowed("Check this upgrade payment's status before continuing.")
        _validate_plan(client.fetch_plan(payment.paystack_plan_code), payment)
        result = client.initialize({
            "email": payment.checkout_email, "amount": payment.expected_amount_cents,
            "currency": payment.currency, "reference": payment.reference, "plan": payment.paystack_plan_code,
            "channels": ["card"], "callback_url": live_callback_url(),
            "metadata": {"studigarden_reference": payment.reference, "tier": payment.tier},
        })
        if result.get("reference") != payment.reference or not valid_authorization_url(result.get("authorization_url")):
            raise PaystackError("Paystack returned an unexpected upgrade checkout. Check its payment status.")
        payment.status, payment.authorization_url = "pending", result["authorization_url"]
        payment.save(update_fields=["status", "authorization_url", "updated_at"])
        return payment


def record_verified_upgrade(user, payment, result, paid_at, change):
    """Called under the normal checkout's user-first lock, after API validation."""
    from .paystack_checkout import _one_month_after

    change = StudyPlanChange.objects.select_for_update().get(pk=change.pk)
    if not (change.user_id == user.pk and change.payment_id == payment.pk and change.kind == "upgrade"
            and change.state == "checkout" and change.from_tier == "grow" and change.to_tier == payment.tier == "bloom"
            and payment.mode == "live" and payment.source == "checkout" and payment.plan == "monthly"
            and payment.expected_amount_cents == change.amount_due_now_cents == change.monthly_amount_cents
            and payment.paystack_plan_code == change.to_plan_code and payment.currency == change.currency == "ZAR"):
        raise UpgradeAttention("upgrade_scope_changed")
    member = StudyMembership.objects.select_for_update().filter(user=user).first()
    conflict = (
        not user.is_active or has_permanent_free_access(user) or change.cancel_requested or _pending_guarantee(user.pk)
        or not member or member.payment_mode != "live" or member.plan != "monthly" or member.tier != "grow"
        or member.paystack_subscription_code not in (None, "", change.from_subscription_code)
        or member.paystack_customer_code != change.customer_code
    )
    payment.status, payment.paystack_transaction_id, payment.verified_at = "succeeded", result["id"], timezone.now()
    payment.period_start, payment.period_end = paid_at, _one_month_after(paid_at)
    if conflict:
        # An accepted refund/account change won the race. Return the new money
        # through discarded-checkout recovery instead of cancelling a newer plan.
        payment.discarded_at = timezone.now()
        change.state, change.last_result = "cancelled", "upgrade_conflict_refund_queued"
        StudyRefund.objects.get_or_create(payment=payment, reason="discarded_checkout", defaults={
            "user": user, "mode": "live", "amount_cents": payment.expected_amount_cents, "currency": "ZAR",
        })
    else:
        funding = StudyPayment.objects.filter(
            user=user, mode="live", tier="grow", plan="monthly", status="succeeded",
            paystack_plan_code=change.from_plan_code, period_start__lte=paid_at, period_end__gt=paid_at,
            verified_at__isnull=False, paystack_transaction_id__isnull=False, discarded_at__isnull=True,
            paystack_subscription_code=change.from_subscription_code,
        ).first()
        if funding:
            change.previous_payment = funding
            change.from_paid_until = funding.period_end
        StudyMembership.objects.filter(pk=member.pk).update(
            tier="bloom", status="active" if payment.period_end > timezone.now() else "expired",
            paid_until=payment.period_end, grace_until=None,
            paystack_customer_code=result["customer"]["customer_code"], paystack_subscription_code=None,
            updated_at=timezone.now(),
        )
        change.state, change.last_result = "settling", "upgrade_payment_verified"
        change.effective_at = paid_at
        change.next_attempt_at = None
    payment.save(update_fields=["status", "paystack_transaction_id", "verified_at", "period_start", "period_end", "discarded_at", "updated_at"])
    change.save()
    return payment


def _upgrade_scope(change):
    payment, previous = change.payment, change.previous_payment
    if not (payment and previous and change.kind == "upgrade"
            and change.from_tier == previous.tier == "grow" and change.to_tier == "bloom"
            and payment.user_id == previous.user_id == change.user_id
            and payment.mode == previous.mode == "live" and payment.source == "checkout" and payment.plan == previous.plan == "monthly"
            and payment.tier == "bloom" and payment.status in {"succeeded", "reversed"} and payment.verified_at
            and payment.paystack_transaction_id and payment.paystack_plan_code == change.to_plan_code
            and payment.expected_amount_cents == change.amount_due_now_cents == change.monthly_amount_cents
            and payment.currency == previous.currency == change.currency == "ZAR"
            and not payment.discarded_at and not previous.discarded_at
            and previous.paystack_plan_code == change.from_plan_code
            and previous.paystack_subscription_code == change.from_subscription_code
            and re.fullmatch(r"SUB_[A-Za-z0-9]+", change.from_subscription_code)):
        raise UpgradeAttention("upgrade_scope_changed")


def stop_previous_upgrade_subscription(client, change):
    """Never use the current membership's cancel method for a historical credit."""
    _upgrade_scope(change)
    if StudyMembership.objects.filter(paystack_subscription_code=change.from_subscription_code).exists():
        raise UpgradeAttention("previous_subscription_is_current")

    def checked():
        value = client.fetch_subscription(change.from_subscription_code)
        if (value.get("subscription_code") != change.from_subscription_code
                or not _matches_subscription(value, change.customer_code, change.from_plan_code, "live")):
            raise UpgradeAttention("previous_subscription_owner_mismatch")
        return value

    subscription = checked()
    if subscription.get("status") not in STOPPED_STATUSES:
        token = subscription.get("email_token")
        if (subscription.get("status") not in RENEWING_STATUSES or not isinstance(token, str)
                or not 1 <= len(token) <= 500 or any(c in token for c in "\r\n")):
            raise UpgradeAttention("previous_subscription_state_unconfirmed")
        try:
            client.disable_subscription(change.from_subscription_code, token)
        except PaystackError:
            pass  # A timeout may follow success; GET the exact remote object.
        subscription = checked()
        if subscription.get("status") not in STOPPED_STATUSES:
            raise PaystackError("Previous renewal cancellation is awaiting confirmation.")
    return change.from_subscription_code


def upgrade_refund_change(refund):
    matches = list(StudyPlanChange.objects.filter(
        user_id=refund.user_id, kind="upgrade", previous_payment_id=refund.payment_id,
        state__in=("settling", "applied", "attention"),
    ).select_related("payment", "previous_payment")[:2])
    if len(matches) != 1:
        raise UpgradeAttention("upgrade_refund_proof_missing")
    change = matches[0]
    _upgrade_scope(change)
    if not change.old_stopped_at:
        raise UpgradeAttention("previous_renewals_not_confirmed_stopped")
    return change


def validate_upgrade_credit(client, change):
    from .paystack_checkout import _validate_transaction

    _upgrade_scope(change)
    result = client.verify(change.payment.reference)
    paid_at = _validate_transaction(result, change.payment)
    if result.get("status") != "success" or result.get("id") != change.payment.paystack_transaction_id or not paid_at:
        raise UpgradeAttention("upgrade_charge_not_verified")
    _period(change.payment, paid_at)
    _, start, end = _verify_lower_payment(client, change.previous_payment, change.customer_code)
    if end != change.from_paid_until:
        raise UpgradeAttention("upgrade_funded_period_mismatch")
    return start <= paid_at < end


def _defer_change(change, result, *, attention=False):
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=change.user_id)
        change = StudyPlanChange.objects.select_for_update().get(pk=change.pk)
        if change.state != "settling":
            return change
        change.attempt_count += 1
        change.state = "attention" if attention else "settling"
        change.last_result = result
        change.next_attempt_at = timezone.now() + timedelta(seconds=min(60 * 2 ** min(change.attempt_count - 1, 6), 3600))
        change.save(update_fields=["state", "attempt_count", "last_result", "next_attempt_at", "updated_at"])
        return change


def process_upgrade_change(change_id):
    client = PaystackLiveClient()
    change = StudyPlanChange.objects.select_related("payment", "previous_payment").get(pk=change_id, kind="upgrade")
    if change.state != "settling" or (change.next_attempt_at and change.next_attempt_at > timezone.now()):
        return change
    try:
        stop_previous_upgrade_subscription(client, change)
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=change.user_id)
            change = StudyPlanChange.objects.select_for_update().select_related("payment", "previous_payment").get(pk=change.pk)
            if change.state != "settling":
                return change
            _upgrade_scope(change)
            change.old_stopped_at = timezone.now()
            change.save(update_fields=["old_stopped_at", "updated_at"])
        # GET verification may be repeated; financial submission belongs only to
        # refund_service, which persists submission intent before its POST.
        completed_refund = StudyRefund.objects.filter(
            payment_id=change.previous_payment_id, status="completed",
        ).exists() and change.previous_payment.status == "reversed"
        funded = False if completed_refund else validate_upgrade_credit(client, change)
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=change.user_id)
            change = StudyPlanChange.objects.select_for_update().get(pk=change.pk)
            if change.state != "settling":
                return change
            result = "previous_payment_already_refunded" if completed_refund else "previous_period_ended"
            if funded:
                existing = StudyRefund.objects.filter(payment_id=change.previous_payment_id).exclude(status="ineligible").first()
                if existing and existing.reason != "upgrade" and existing.status != "completed":
                    raise UpgradeAttention("previous_refund_already_pending")
                if not existing:
                    StudyRefund.objects.create(
                        user_id=change.user_id, payment_id=change.previous_payment_id, reason="upgrade", mode="live",
                        amount_cents=change.previous_payment.expected_amount_cents, currency="ZAR",
                    )
                result = "upgrade_credit_queued" if not existing or existing.reason == "upgrade" else "previous_payment_already_refunded"
            change.state, change.last_result = "applied", result
            change.applied_at, change.next_attempt_at = timezone.now(), None
            change.save(update_fields=["state", "last_result", "applied_at", "next_attempt_at", "updated_at"])
            return change
    except UpgradeAttention as exc:
        return _defer_change(change, str(exc), attention=True)
    except PaystackError:
        if change.payment.verified_at and change.payment.verified_at < timezone.now() - timedelta(hours=24):
            return _defer_change(change, "upgrade_settlement_needs_attention", attention=True)
        return _defer_change(change, "upgrade_provider_confirmation_pending")
    except IntegrityError:
        return _defer_change(change, "upgrade_identity_conflict", attention=True)


def process_upgrade_batch(limit=5):
    if not live_billing_enabled():
        raise PaystackError("Live billing is disabled.")
    due = StudyPlanChange.objects.filter(kind="upgrade", state="settling").filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()),
    ).order_by("requested_at", "pk").values_list("pk", flat=True)[:limit]
    outcomes = []
    for pk in list(due):
        try:
            change = process_upgrade_change(pk)
        except DatabaseError:
            raise
        except Exception:
            change = _defer_change(StudyPlanChange.objects.get(pk=pk), "upgrade_processor_error", attention=True)
        outcomes.append((change.pk, change.state, change.last_result))
    return outcomes

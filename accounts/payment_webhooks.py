"""Mode-isolated billing reconciliation; all Paystack requests are GETs.

An unknown charge alone is not proof of a subscription renewal. Require its
signed invoice, the subscription's current invoice, and transaction verification.
Only absolute, validated invoice periods grant access, never arrival order.
"""

import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment, StudyPlanChange
from .payment_service import CheckoutNotAllowed
from .paystack_checkout import PaymentNotFound, reconcile_discarded_checkout, reconcile_upgrade_checkout, verify_test_checkout, verify_live_checkout
from .paystack_client import PaystackError, PaystackTestClient, PaystackLiveClient
from .subscription_service import STOPPED_STATUSES
from .subscription_webhooks import (
    State, _Ignore, _Retry, _canonical_subscription, _code, _due, _finish,
    _finish_locked, _owner, _positive_id, _proof,
)


PAYMENT_EVENTS = ("charge.success", "invoice.create", "invoice.update", "invoice.payment_failed")


def _datetime(value):
    try:
        parsed = parse_datetime(value) if isinstance(value, str) else None
        return parsed if parsed and timezone.is_aware(parsed) else None
    except (TypeError, ValueError):
        return None


def _initial_payment(member, subscription):
    from .membership_proof import membership_payment
    payment = membership_payment(member, subscription.plan_code)
    if not payment or not payment.checkout_email or payment.currency != "ZAR":
        raise _Retry("checkout_not_verified")
    return payment


def _invoice(subscription, snapshot, initial):
    invoice = subscription.latest_invoice
    if not isinstance(invoice, dict) or invoice.get("invoice_code") != snapshot["invoice_code"]:
        # No undocumented invoice endpoint or guessing from email/plan. An old
        # invoice no longer available at Paystack requires later reconciliation.
        raise _Retry("provider_invoice_unavailable")
    if invoice.get("domain") != subscription.mode:
        raise _Ignore("provider_mode_mismatch")
    if "object_id" in snapshot and (
        not _positive_id(snapshot["object_id"]) or type(invoice.get("id")) is not int
        or snapshot["object_id"] != invoice["id"]
    ):
        raise _Ignore("invoice_identity_mismatch")
    for field, expected in (("subscription", subscription.object_id), ("customer", subscription.customer_id)):
        if field in invoice and (
            not _positive_id(expected) or type(invoice[field]) is not int or invoice[field] != expected
        ):
            raise _Ignore("invoice_ownership_mismatch")
    amount = invoice.get("amount")
    if (
        type(amount) is not int or amount != initial.expected_amount_cents
        or invoice.get("currency", "ZAR") != "ZAR"
        or (snapshot.get("amount_cents") is not None and snapshot["amount_cents"] != amount)
        or snapshot.get("currency", "ZAR") != "ZAR"
    ):
        raise _Ignore("invoice_price_mismatch")
    start, end = _datetime(invoice.get("period_start")), _datetime(invoice.get("period_end"))
    if (
        not start or not end or not timedelta(days=27) <= end - start <= timedelta(days=32)
        or start > timezone.now() + timedelta(minutes=5)
        or start < initial.created_at - timedelta(minutes=5)
    ):
        raise _Retry("invoice_period_invalid")
    for field, expected in (("period_start", start), ("period_end", end)):
        if field in snapshot and _datetime(snapshot[field]) != expected:
            raise _Ignore("invoice_period_mismatch")
    paid = invoice.get("paid")
    if type(paid) not in (bool, int) or paid not in (False, True, 0, 1):
        raise _Retry("invoice_state_unconfirmed")
    status = invoice.get("status")
    if paid and status == "success":
        successful = True
    elif not paid and status in ("failed", "attention"):
        successful = False
    else:
        raise _Retry("invoice_state_unconfirmed")
    return invoice, start, end, successful


def _verified_charge(client, snapshot, invoice, initial, subscription, start, end):
    reference = snapshot.get("transaction_reference")
    if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z0-9._=-]{1,100}", reference):
        raise _Retry("invoice_charge_missing")
    if not _positive_id(invoice.get("transaction")):
        raise _Retry("invoice_transaction_unconfirmed")
    result = client.verify(reference)
    customer = result.get("customer")
    codes = []
    for value in (result.get("plan"), result.get("plan_object")):
        if value:
            codes.append(value.get("plan_code") if isinstance(value, dict) else value)
        if isinstance(value, dict) and value.get("domain") not in (None, subscription.mode):
            raise _Ignore("transaction_mode_mismatch")
    if (
        result.get("domain") != subscription.mode or result.get("reference") != reference
        or not _positive_id(result.get("id"))
        or type(result.get("amount")) is not int or result["amount"] != initial.expected_amount_cents
        or result.get("currency") != "ZAR"
        or not codes or any(code != subscription.plan_code for code in codes)
        or not isinstance(customer, dict) or customer.get("domain") not in (None, subscription.mode)
        or customer.get("customer_code") != subscription.customer_code
        or not isinstance(customer.get("email"), str)
        or customer["email"].casefold() != initial.checkout_email.casefold()
    ):
        raise _Ignore("transaction_mismatch")
    if result.get("status") != "success":
        raise _Retry("transaction_not_successful")
    for identifier in (snapshot.get("transaction_id"), invoice.get("transaction")):
        if identifier is not None and (not _positive_id(identifier) or identifier != result["id"]):
            raise _Ignore("invoice_transaction_mismatch")
    paid_at = _datetime(result.get("paid_at"))
    if (
        not paid_at or paid_at > timezone.now() + timedelta(minutes=5)
        or paid_at < start - timedelta(minutes=5) or paid_at > end + timedelta(minutes=5)
    ):
        raise _Retry("transaction_time_invalid")
    return result


def _apply_invoice(receipt_id, member, subscription, initial, start, end, successful, charge):
    mode = subscription.mode
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=member.user_id)
        receipt = PaystackWebhookReceipt.objects.select_for_update().get(pk=receipt_id)
        if not _due(receipt):
            return receipt
        if mode == "live":
            if StudyPlanChange.objects.filter(
                user=user, kind="resume", from_subscription_code=subscription.code,
                state__in=("queued", "submitting", "attention"),
            ).exists():
                raise _Retry("resume_confirmation_pending")
            from .plan_change_payments import _retired_from_change
            if _retired_from_change(subscription, start, end):
                # Another worker may have retired this renewal after the first
                # lookup. Reprocess through recovery; never extend the old tier.
                raise _Retry("plan_change_reconciliation_required")
        current = StudyMembership.objects.select_for_update().get(pk=member.pk)
        _proof(current, subscription)
        if _initial_payment(current, subscription).pk != initial.pk:
            raise _Retry("membership_changed")
        invoice_code = receipt.snapshot["invoice_code"]
        payment = StudyPayment.objects.select_for_update().filter(mode=mode, paystack_invoice_code=invoice_code).first()
        if payment and (
            payment.user_id != user.pk or payment.source != "renewal"
            or payment.tier != current.tier or payment.plan != "monthly" or payment.currency != "ZAR"
            or payment.paystack_plan_code != subscription.plan_code
            or payment.paystack_subscription_code != subscription.code
            or payment.period_start != start or payment.period_end != end
            or payment.expected_amount_cents != initial.expected_amount_cents
        ):
            raise _Ignore("invoice_already_owned")
        if payment and payment.status in ("succeeded", "reversed"):
            if charge and (payment.reference != charge["reference"] or payment.paystack_transaction_id != charge["id"]):
                raise _Ignore("invoice_transaction_conflict")
            return _finish_locked(receipt, State.PROCESSED, "payment_already_recorded")
        if charge:
            existing = StudyPayment.objects.filter(
                Q(reference=charge["reference"]) | Q(mode=mode, paystack_transaction_id=charge["id"]),
            ).exclude(pk=payment.pk if payment else None).first()
            if existing:
                if (
                    existing.user_id == user.pk and existing.mode == mode
                    and existing.reference == charge["reference"] and existing.paystack_transaction_id == charge["id"]
                    and existing.status == "succeeded"
                    and (existing.source == "checkout" or existing.paystack_invoice_code == invoice_code)
                ):
                    return _finish_locked(receipt, State.PROCESSED, "payment_already_recorded")
                raise _Ignore("transaction_already_owned")
        if payment is None:
            payment = StudyPayment(
                user=user, mode=mode, source="renewal", tier=current.tier, plan="monthly",
                paystack_plan_code=subscription.plan_code, checkout_email=initial.checkout_email,
                paystack_invoice_code=invoice_code, paystack_subscription_code=subscription.code,
                expected_amount_cents=initial.expected_amount_cents, currency="ZAR",
                period_start=start, period_end=end,
            )
        payment.status = "succeeded" if successful else "failed"
        if charge:
            payment.reference = charge["reference"]
            payment.paystack_transaction_id = charge["id"]
            payment.verified_at = timezone.now()
        payment.save()
        stopped = current.status == "non_renewing" or subscription.status in STOPPED_STATUSES
        fields = []
        if not current.paystack_subscription_code:
            current.paystack_subscription_code = subscription.code
            fields.append("paystack_subscription_code")
        if successful:
            # Absolute end date, not +one month on the present entitlement. This
            # prevents replay, changed JSON, or out-of-order delivery stacking time.
            if current.paid_until is None or end > current.paid_until:
                current.paid_until = end
                fields.append("paid_until")
            newer_failure = StudyPayment.objects.filter(
                user=user, mode=mode, source="renewal", paystack_subscription_code=subscription.code,
                status="failed", period_end__gt=end,
            ).exists()
            if stopped:
                current.status = "non_renewing" if current.paid_until > timezone.now() else "expired"
            elif newer_failure:
                current.status = "past_due"
            else:
                current.status = "active" if current.paid_until > timezone.now() else "expired"
            fields.append("status")
            if not newer_failure:
                current.grace_until = None
                fields.append("grace_until")
            result = "renewal_verified"
        else:
            # A stale failed invoice cannot undo a later paid period or cancelled
            # renewal. Never remove paid time or create a new grace allowance.
            if not stopped and (current.paid_until is None or current.paid_until < end):
                current.status = "past_due"
                fields.append("status")
            result = "renewal_failed"
        if fields:
            current.save(update_fields=[*fields, "updated_at"])
        return _finish_locked(receipt, State.PROCESSED, result)


def _charge_receipt(receipt):
    reference = receipt.snapshot.get("transaction_reference")
    if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z0-9._=-]{1,100}", reference):
        raise _Ignore("invalid_transaction_reference")
    payment = StudyPayment.objects.filter(reference=reference, mode=receipt.mode).first()
    if not payment:
        raise _Retry("awaiting_verified_invoice")
    if payment.source == "renewal":
        if payment.status != "succeeded":
            raise _Retry("awaiting_verified_invoice")
        if receipt.snapshot.get("transaction_id", payment.paystack_transaction_id) != payment.paystack_transaction_id:
            raise _Ignore("transaction_mismatch")
        return _finish(receipt.pk, State.PROCESSED, "payment_already_recorded")
    try:
        verify = verify_live_checkout if receipt.mode == "live" else verify_test_checkout
        if receipt.mode == "live" and payment.discarded_at:
            payment = reconcile_discarded_checkout(payment, PaystackLiveClient())
        elif receipt.mode == "live" and StudyPlanChange.objects.filter(payment=payment, kind__in=("upgrade", "restart")).exists():
            payment = reconcile_upgrade_checkout(payment, PaystackLiveClient())
        else:
            payment = verify(user=payment.user, reference=reference)
    except (CheckoutNotAllowed, PaymentNotFound):
        raise _Retry("checkout_not_ready") from None
    if payment.discarded_at and payment.status in {"succeeded", "reversed"}:
        return _finish(receipt.pk, State.PROCESSED, "discarded_payment_refund_queued")
    if payment.status != "succeeded":
        raise _Retry("transaction_not_successful")
    return _finish(receipt.pk, State.PROCESSED, "checkout_verified")


def process_test_payment_receipt(receipt_id):
    return _process_payment_receipt(receipt_id, PaystackTestClient(), "test")


def process_live_payment_receipt(receipt_id):
    return _process_payment_receipt(receipt_id, PaystackLiveClient(), "live")


def _process_payment_receipt(receipt_id, client, mode):
    if not _positive_id(receipt_id):
        raise ValueError("A valid stored receipt ID is required.")
    receipt = PaystackWebhookReceipt.objects.filter(pk=receipt_id, mode=mode, event_type__in=PAYMENT_EVENTS).first()
    if receipt is None:
        raise ValueError("Only stored test payment notifications can be processed here.")
    if not _due(receipt):
        return receipt
    try:
        snapshot = receipt.snapshot
        if (
            not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int
            or snapshot["schema_version"] != 1 or snapshot.get("domain") != mode
        ):
            raise _Ignore("invalid_receipt")
        if receipt.event_type == "charge.success":
            return _charge_receipt(receipt)
        if not _code(snapshot.get("invoice_code"), "INV_") or not _code(snapshot.get("subscription_code"), "SUB_"):
            raise _Ignore("invalid_invoice_identifier")
        if receipt.event_type == "invoice.create":
            return _finish(receipt.pk, State.PROCESSED, "invoice_scheduled")
        hint = {
            name: snapshot[name] for name in (
                "schema_version", "domain", "subscription_code", "customer_code", "plan_code",
            ) if name in snapshot
        }
        if "subscription_id" in snapshot:
            hint["object_id"] = snapshot["subscription_id"]
        subscription = _canonical_subscription(client, hint)
        if mode == "live":
            from .plan_change_payments import process_plan_change_invoice
            result = process_plan_change_invoice(receipt, client, subscription)
            if result is not None:
                return result
        member = _owner(subscription)
        initial = _initial_payment(member, subscription)
        invoice, start, end, successful = _invoice(subscription, snapshot, initial)
        charge = _verified_charge(client, snapshot, invoice, initial, subscription, start, end) if successful else None
        if not successful and subscription.status != "attention":
            raise _Retry("failure_not_current")
        return _apply_invoice(receipt.pk, member, subscription, initial, start, end, successful, charge)
    except _Ignore as outcome:
        return _finish(receipt.pk, State.IGNORED, str(outcome))
    except _Retry as outcome:
        return _finish(receipt.pk, State.RETRY, str(outcome))
    except PaystackError:
        return _finish(receipt.pk, State.RETRY, "provider_unavailable")
    except IntegrityError:
        return _finish(receipt.pk, State.RETRY, "payment_identity_conflict")
    except (StudyMembership.DoesNotExist, get_user_model().DoesNotExist):
        return _finish(receipt.pk, State.RETRY, "membership_not_ready")

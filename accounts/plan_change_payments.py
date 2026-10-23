"""Verify scheduled first debits and recover charges on retired billing.

Notification contents are hints only. The canonical subscription, invoice and
transaction must agree before recording access or a durable refund instruction.
All provider operations in this module are GETs.
"""

from datetime import timedelta
from types import SimpleNamespace
import re

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .access import has_permanent_free_access
from .downgrade_service import ScheduleAttention, _scope
from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment, StudyPlanChange, StudyRefund
from .paystack_checkout import _validate_transaction
from .subscription_service import STOPPED_STATUSES
from .subscription_webhooks import State, _Ignore, _Retry, _due, _finish, _finish_locked


def _expected(change, *, lower):
    previous = change.previous_payment
    return SimpleNamespace(
        expected_amount_cents=change.monthly_amount_cents if lower else previous.expected_amount_cents,
        checkout_email=change.billing_email, created_at=change.requested_at if lower else previous.created_at,
    )


def _verified_invoice(client, snapshot, subscription, change, *, lower):
    from .payment_webhooks import _invoice, _verified_charge
    expected = _expected(change, lower=lower)
    invoice, start, end, successful = _invoice(subscription, snapshot, expected)
    hint = dict(snapshot)
    if successful and not hint.get("transaction_reference"):
        identifier = invoice.get("transaction")
        fetched = client.fetch_transaction(identifier)
        if fetched.get("domain") != "live" or fetched.get("id") != identifier:
            raise _Ignore("scheduled_transaction_identifier_mismatch")
        hint["transaction_reference"] = fetched.get("reference")
    charge = _verified_charge(client, hint, invoice, expected, subscription, start, end) if successful else None
    if not successful and subscription.status != "attention":
        raise _Retry("failure_not_current")
    return start, end, successful, charge


def _record_payment(change, receipt, subscription, start, end, charge, *, lower):
    amount = change.monthly_amount_cents if lower else change.previous_payment.expected_amount_cents
    tier = change.to_tier if lower else change.from_tier
    invoice_code = receipt.snapshot["invoice_code"]
    payment = StudyPayment.objects.select_for_update().filter(mode="live", paystack_invoice_code=invoice_code).first()
    if payment is None and charge:
        payment = StudyPayment.objects.select_for_update().filter(
            Q(reference=charge["reference"]) | Q(mode="live", paystack_transaction_id=charge["id"]),
        ).first()
    if payment and (
        payment.user_id != change.user_id or payment.mode != "live" or payment.tier != tier
        or payment.plan != "monthly" or payment.currency != "ZAR"
        or payment.expected_amount_cents != amount or payment.paystack_plan_code != subscription.plan_code
        or payment.paystack_subscription_code not in ("", subscription.code)
        or (payment.paystack_invoice_code not in (None, "", invoice_code))
        or (payment.period_start is not None and payment.period_start != start)
        or (payment.period_end is not None and payment.period_end != end)
    ):
        raise _Ignore("plan_change_invoice_already_owned")
    if payment and payment.status in {"succeeded", "reversed"}:
        if charge and (payment.reference != charge["reference"] or payment.paystack_transaction_id != charge["id"]):
            raise _Ignore("plan_change_transaction_conflict")
        return payment
    if payment is None:
        payment = StudyPayment(
            user_id=change.user_id, mode="live", source="renewal", tier=tier, plan="monthly", currency="ZAR",
            paystack_plan_code=subscription.plan_code, checkout_email=change.billing_email,
            expected_amount_cents=amount, paystack_subscription_code=subscription.code,
            paystack_invoice_code=invoice_code, period_start=start, period_end=end,
        )
    payment.status = "succeeded" if charge else "failed"
    if charge:
        payment.reference, payment.paystack_transaction_id = charge["reference"], charge["id"]
        payment.verified_at = timezone.now()
    payment.save()
    return payment


def _queue_recovery(change, payment):
    # The per-payment financial-request constraint prevents a guarantee, upgrade
    # credit and retired-charge recovery from returning the same money twice.
    existing = StudyRefund.objects.filter(payment=payment).exclude(status="ineligible").first()
    if existing:
        return existing
    payment.discarded_at = payment.discarded_at or timezone.now()
    payment.save(update_fields=["discarded_at", "updated_at"])
    return StudyRefund.objects.create(
        user_id=change.user_id, payment=payment, plan_change=change, reason="retired_subscription",
        mode="live", amount_cents=payment.expected_amount_cents, currency="ZAR",
    )


def _retired_from_change(subscription, start, end):
    changes = StudyPlanChange.objects.filter(
        from_subscription_code=subscription.code, customer_code=subscription.customer_code,
        from_plan_code=subscription.plan_code,
    ).select_related("previous_payment", "payment").order_by("-requested_at", "-pk")
    change = changes.first()
    if not change or (change.state == "cancelled" and change.restore_current):
        return None
    if change.kind == "upgrade":
        if (not change.payment or change.payment.status not in {"succeeded", "reversed"}
                or not change.payment.verified_at or change.payment.discarded_at):
            return None
        return change if end > change.effective_at else None
    if change.kind == "downgrade" and change.old_stopped_at and start >= change.effective_at - timedelta(seconds=1):
        return change
    return None


def process_plan_change_invoice(receipt, client, subscription):
    """Return None for ordinary invoices; otherwise return a verified outcome."""
    if subscription.mode != "live":
        return None
    latest = subscription.latest_invoice
    from .payment_webhooks import _datetime
    if not isinstance(latest, dict):
        return None
    start, end = _datetime(latest.get("period_start")), _datetime(latest.get("period_end"))
    if not start or not end:
        return None
    retired = _retired_from_change(subscription, start, end)
    lower_change = StudyPlanChange.objects.filter(
        kind="downgrade", to_subscription_code=subscription.code, to_tier="grow",
        customer_code=subscription.customer_code, to_plan_code=subscription.plan_code,
    ).select_related("previous_payment", "payment").first()
    lower = retired is None
    change = retired or lower_change
    if not change:
        return None
    if lower and change.state == "applied" and not change.cancel_requested:
        return None  # Ordinary later renewal, proved by this change's first debit.
    start, end, successful, charge = _verified_invoice(client, receipt.snapshot, subscription, change, lower=lower)
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=change.user_id)
        receipt = PaystackWebhookReceipt.objects.select_for_update().get(pk=receipt.pk)
        if not _due(receipt):
            return receipt
        change = StudyPlanChange.objects.select_for_update().select_related("previous_payment", "payment").get(pk=change.pk)
        member = StudyMembership.objects.select_for_update().get(user_id=user.pk)
        first_refund = StudyRefund.objects.filter(user=user, mode="live", reason="first_payment").exclude(
            status__in=("completed", "ineligible"),
        ).first()
        if lower and first_refund and (first_refund.status == "requested" or (
                first_refund.status == "attention" and not first_refund.approved_at)):
            raise _Retry("refund_eligibility_pending")
        if lower and change.to_subscription_code != subscription.code:
            raise _Retry("scheduled_subscription_changed")
        payment = _record_payment(change, receipt, subscription, start, end, charge, lower=lower)
        if not successful:
            if lower:
                change.last_result = "lower_payment_failed"
                change.save(update_fields=["last_result", "updated_at"])
            return _finish_locked(receipt, State.PROCESSED, "scheduled_payment_failed")
        if not lower:
            if change.kind == "upgrade" and payment.pk == change.previous_payment_id:
                return _finish_locked(receipt, State.PROCESSED, "payment_already_recorded")
            _queue_recovery(change, payment)
            return _finish_locked(receipt, State.PROCESSED, "retired_payment_refund_queued")
        paid_at = _datetime(charge.get("paid_at"))
        early = start < change.effective_at - timedelta(seconds=1) or paid_at < change.effective_at - timedelta(seconds=1)
        cancelled_before_charge = bool(
            (change.cancel_requested and not change.cancel_requested_at)
            or (change.cancel_requested_at and paid_at > change.cancel_requested_at)
        )
        conflict = (not user.is_active or has_permanent_free_access(user) or early or cancelled_before_charge
                    or payment.discarded_at or payment.status == "reversed")
        if not conflict and change.payment_id == payment.pk:
            return _finish_locked(receipt, State.PROCESSED, "payment_already_recorded")
        if not conflict:
            try:
                _scope(change, member)
            except ScheduleAttention:
                conflict = True
            if member.status not in {"non_renewing", "expired"}:
                conflict = True
        first_refund_pending = bool(first_refund)
        if conflict or first_refund_pending:
            _queue_recovery(change, payment)
            change.cancel_requested = True
            change.cancel_requested_at = change.cancel_requested_at or timezone.now()
            if not change.cancelled_at:
                change.restore_current = False
            if not change.cancelled_at:
                change.state, change.next_attempt_at = "settling", None
            change.last_result = "cancelled_lower_payment_refund_queued"
            change.save()
            return _finish_locked(receipt, State.PROCESSED, "cancelled_lower_payment_refund_queued")
        if timezone.now() < change.effective_at - timedelta(seconds=1):
            raise _Retry("scheduled_date_not_reached")
        stopped = change.cancel_requested or subscription.status in STOPPED_STATUSES
        member.tier, member.paystack_subscription_code = "grow", subscription.code
        member.paid_until, member.grace_until = end, None
        member.status = "non_renewing" if stopped else ("active" if end > timezone.now() else "expired")
        member.save(update_fields=["tier", "paystack_subscription_code", "paid_until", "grace_until", "status", "updated_at"])
        change.payment, change.applied_at = payment, timezone.now()
        change.state = ("cancelled" if change.cancelled_at else "settling") if change.cancel_requested else "applied"
        change.next_attempt_at, change.last_result = None, "lower_payment_verified"
        change.save()
        return _finish_locked(receipt, State.PROCESSED, "lower_payment_verified")


def scheduled_subscription_metadata(receipt, subscription):
    change = StudyPlanChange.objects.filter(
        kind="downgrade", to_subscription_code=subscription.code, customer_code=subscription.customer_code,
        to_plan_code=subscription.plan_code, payment__isnull=True,
    ).first()
    if not change:
        return None
    # Metadata can never switch the membership or invent a successful debit.
    return _finish(receipt.pk, State.PROCESSED, "scheduled_subscription_metadata_only")


def retired_refund_change(refund):
    from .refund_service import _Attention
    change, payment = refund.plan_change, refund.payment
    if not (change and change.user_id == payment.user_id == refund.user_id
            and payment.mode == "live" and payment.verified_at and payment.paystack_transaction_id
            and payment.discarded_at and payment.period_start and payment.period_end
            and payment.currency == change.currency == "ZAR"):
        raise _Attention("retired_refund_proof_missing")
    if payment.paystack_subscription_code == change.from_subscription_code:
        valid = (payment.tier == change.from_tier and payment.paystack_plan_code == change.from_plan_code
                 and payment.expected_amount_cents == change.previous_payment.expected_amount_cents
                 and (change.old_stopped_at or (change.kind == "upgrade" and change.payment_id)))
        if change.kind == "downgrade":
            valid = valid and payment.period_start >= change.effective_at - timedelta(seconds=1)
            if change.state == "cancelled" and change.restore_current:
                valid = False
        elif change.kind == "upgrade":
            upgraded = change.payment
            valid = bool(valid and upgraded and upgraded.user_id == change.user_id and upgraded.mode == "live"
                         and upgraded.status in {"succeeded", "reversed"} and upgraded.verified_at
                         and not upgraded.discarded_at and payment.period_end > change.effective_at)
    else:
        valid = (change.kind == "downgrade" and change.cancel_requested
                 and payment.paystack_subscription_code == change.to_subscription_code
                 and payment.paystack_plan_code == change.to_plan_code and payment.tier == change.to_tier
                 and payment.expected_amount_cents == change.monthly_amount_cents)
    if not valid:
        raise _Attention("retired_refund_scope_changed")
    return change


def assess_retired_refund(client, refund):
    from .refund_service import _Attention
    change = retired_refund_change(refund)
    result = client.verify(refund.payment.reference)
    paid_at = _validate_transaction(result, refund.payment)
    if (result.get("status") != "success" or result.get("id") != refund.payment.paystack_transaction_id
            or not paid_at or result["customer"]["customer_code"] != change.customer_code):
        raise _Attention("retired_charge_not_verified")
    return paid_at


def stop_retired_refund_subscription(client, refund):
    from .downgrade_cancellation import stop_change_subscription
    from .refund_service import _Attention
    change = retired_refund_change(refund)
    current = StudyMembership.objects.filter(paystack_subscription_code=refund.payment.paystack_subscription_code).first()
    if current and (current.user_id != change.user_id or current.status not in {"non_renewing", "expired"}):
        raise _Attention("retired_subscription_became_current")
    try:
        return stop_change_subscription(client, change, refund.payment.paystack_subscription_code)
    except ScheduleAttention as exc:
        raise _Attention(str(exc)) from None

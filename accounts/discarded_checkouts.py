"""Resolve only the subscription belonging to a discarded, verified charge.

An exact canonical invoice/transaction link wins. A unique customer/plan match
is usable only if there has never been another checkout for that same pair.
Ambiguity must never cancel the customer's current subscription.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import StudyMembership, StudyPayment
from .paystack_checkout import _positive_integer, _validate_transaction
from .paystack_client import PaystackError
from .subscription_service import RENEWING_STATUSES, STOPPED_STATUSES, _matches_subscription


def invoice_transaction_ids(subscription):
    invoices = subscription.get("invoices", [])
    invoices = list(invoices) if isinstance(invoices, list) else []
    recent = subscription.get("most_recent_invoice")
    if isinstance(recent, dict):
        invoices.append(recent)
    result = set()
    for invoice in invoices:
        if not isinstance(invoice, dict) or invoice.get("domain") not in (None, "live"):
            continue
        if "subscription" in invoice and invoice["subscription"] != subscription.get("id"):
            continue
        charge = invoice.get("transaction")
        if isinstance(charge, dict):
            if charge.get("domain") not in (None, "live"):
                continue
            charge = charge.get("id")
        if _positive_integer(charge):
            result.add(charge)
    return result


def _created_near_payment(subscription, paid_at):
    try:
        created = parse_datetime(subscription.get("createdAt") or subscription.get("created_at") or "")
        return bool(created and timezone.is_aware(created) and abs(created - paid_at) <= timedelta(minutes=5))
    except (TypeError, ValueError):
        return False


def cancel_discarded_subscription(client, refund):
    # Same user-first lock order as checkout/normal cancellation. No local
    # membership is edited, even if the abandoned purchase had the same tier.
    from .refund_service import _Attention

    payment = refund.payment
    charge = client.verify(payment.reference)
    paid_at = _validate_transaction(charge, payment)
    if not paid_at or charge.get("id") != payment.paystack_transaction_id:
        raise _Attention("discarded_payment_not_verified")
    customer_code = charge["customer"]["customer_code"]
    customer = client.fetch_customer(customer_code)
    if not (customer.get("domain") == "live" and customer.get("customer_code") == customer_code
            and _positive_integer(customer.get("id"))):
        raise PaystackError("The discarded payment's customer is not confirmed.")
    listed = client.list_customer_subscriptions(customer["id"])
    if len(listed) >= 100:
        raise _Attention("discarded_subscription_ambiguous")
    candidates = {}
    for item in listed:
        if not _matches_subscription(item, customer_code, payment.paystack_plan_code, "live"):
            continue
        code = item["subscription_code"]
        canonical = client.fetch_subscription(code)
        if (canonical.get("subscription_code") != code
                or not _matches_subscription(canonical, customer_code, payment.paystack_plan_code, "live")):
            raise _Attention("discarded_subscription_scope_mismatch")
        candidates[code] = canonical

    exact = [s for s in candidates.values() if payment.paystack_transaction_id in invoice_transaction_ids(s)]
    if exact:
        matches = exact
    else:
        competing = StudyPayment.objects.filter(
            mode="live", source="checkout", paystack_plan_code=payment.paystack_plan_code,
        ).filter(Q(user_id=payment.user_id) | Q(checkout_email__iexact=payment.checkout_email)).exclude(pk=payment.pk).exists()
        matches = [] if competing else [
            s for s in candidates.values()
            if not invoice_transaction_ids(s) and _created_near_payment(s, paid_at)
        ]
    if len(matches) != 1:
        raise PaystackError("The discarded checkout's subscription is not uniquely confirmed yet.")
    subscription = matches[0]
    code = subscription["subscription_code"]
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=payment.user_id)
        payment = StudyPayment.objects.select_for_update().get(pk=payment.pk)
        if not payment.discarded_at or payment.status != "succeeded":
            raise _Attention("discarded_payment_scope_changed")
        if StudyMembership.objects.filter(paystack_subscription_code=code).exists():
            raise _Attention("discarded_subscription_is_current")
        if refund.cancelled_subscription_code and refund.cancelled_subscription_code != code:
            raise _Attention("discarded_subscription_identity_changed")
        status = subscription.get("status")
        if status not in STOPPED_STATUSES:
            token = subscription.get("email_token")
            if (status not in RENEWING_STATUSES or not isinstance(token, str)
                    or not 1 <= len(token) <= 500 or any(c in token for c in "\r\n")):
                raise PaystackError("Cancellation details are not confirmed yet.")
            try:
                client.disable_subscription(code, token)
            except PaystackError:
                canonical = client.fetch_subscription(code)
                if not (canonical.get("subscription_code") == code
                        and _matches_subscription(canonical, customer_code, payment.paystack_plan_code, "live")
                        and canonical.get("status") in STOPPED_STATUSES):
                    raise PaystackError("Discarded subscription cancellation is not confirmed.") from None
        return code

"""Reconcile mode-isolated subscription events using the provider's current state.

Only GET is used at Paystack. This step links subscriptions and mirrors stopped
renewals; it never records a payment, extends paid access or reactivates a plan.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment
from .paystack_client import PaystackError, PaystackTestClient, PaystackLiveClient
from .subscription_service import RENEWING_STATUSES, STOPPED_STATUSES, _matches_subscription


SUBSCRIPTION_EVENTS = ("subscription.create", "subscription.not_renew", "subscription.disable")
State = PaystackWebhookReceipt.ProcessingStatus
TERMINAL_STATES = {State.PROCESSED, State.IGNORED}


class _Retry(Exception):
    pass


class _Ignore(Exception):
    pass


@dataclass(frozen=True)
class _Subscription:
    code: str
    customer_code: str
    plan_code: str
    status: str
    created_at: datetime | None
    object_id: int | None = None
    customer_id: int | None = None
    latest_invoice: dict | None = None
    mode: str = "test"
    invoice_transaction_ids: frozenset = frozenset()


def _code(value, prefix):
    return isinstance(value, str) and len(value) <= 100 and bool(re.fullmatch(prefix + r"[A-Za-z0-9]+", value))


def _positive_id(value):
    return type(value) is int and 0 < value <= 9_223_372_036_854_775_807


def _due(receipt):
    return receipt.processing_status not in TERMINAL_STATES and (
        receipt.next_attempt_at is None or receipt.next_attempt_at <= timezone.now()
    )


def _finish_locked(receipt, state, code):
    now = timezone.now()
    receipt.processing_status = state
    receipt.attempt_count = min(receipt.attempt_count + 1, 2_147_483_647)
    receipt.last_result = code  # Internal constant only, never provider text.
    receipt.processed_at = None if state == State.RETRY else now
    receipt.next_attempt_at = (
        now + timedelta(seconds=min(60 * 2 ** min(receipt.attempt_count - 1, 6), 3600))
        if state == State.RETRY else None
    )
    receipt.save(update_fields=[
        "processing_status", "attempt_count", "last_result", "processed_at", "next_attempt_at",
    ])
    return receipt


def _finish(receipt_id, state, code):
    with transaction.atomic():
        receipt = PaystackWebhookReceipt.objects.select_for_update().get(pk=receipt_id)
        if not _due(receipt):
            return receipt
        return _finish_locked(receipt, state, code)


def _canonical_subscription(client, snapshot):
    mode = client.mode
    if (
        not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int
        or snapshot["schema_version"] != 1 or snapshot.get("domain") != mode
    ):
        raise _Ignore("invalid_receipt")
    code = snapshot.get("subscription_code")
    object_id = snapshot.get("object_id")
    if code is not None and not _code(code, "SUB_"):
        raise _Ignore("invalid_subscription_code")
    if not code and not _positive_id(object_id):
        raise _Ignore("missing_subscription_identifier")
    response = client.fetch_subscription(code or str(object_id))
    if response.get("domain") != mode:
        raise _Ignore("provider_mode_mismatch")
    customer = response.get("customer")
    plan = response.get("plan")
    if not isinstance(customer, dict) or not isinstance(plan, dict):
        raise _Retry("provider_shape_invalid")
    customer_code, plan_code = customer.get("customer_code"), plan.get("plan_code")
    if not (
        _code(customer_code, "CUS_") and _code(plan_code, "PLN_")
        and _matches_subscription(response, customer_code, plan_code, mode)
    ):
        raise _Retry("provider_ownership_invalid")
    if (
        (code and response.get("subscription_code") != code)
        or (object_id is not None and (
            not _positive_id(object_id) or type(response.get("id")) is not int or response["id"] != object_id
        ))
        or (snapshot.get("customer_code") is not None and snapshot["customer_code"] != customer_code)
        or (snapshot.get("plan_code") is not None and snapshot["plan_code"] != plan_code)
    ):
        raise _Ignore("notification_mismatch")
    status = response.get("status")
    if not isinstance(status, str) or status not in RENEWING_STATUSES | STOPPED_STATUSES:
        raise _Retry("unsupported_provider_state")
    try:
        created = parse_datetime(response.get("createdAt") or response.get("created_at") or "")
        if created is not None and timezone.is_naive(created):
            created = None
    except (TypeError, ValueError):
        created = None
    from .discarded_checkouts import invoice_transaction_ids
    return _Subscription(
        response["subscription_code"], customer_code, plan_code, status, created,
        response.get("id"), customer.get("id"), response.get("most_recent_invoice"), mode,
        frozenset(invoice_transaction_ids(response)) if mode == "live" else frozenset(),
    )


def _proof(membership, subscription):
    if (
        membership.payment_mode != subscription.mode
        or membership.plan != StudyMembership.Plan.MONTHLY
        or membership.paystack_customer_code != subscription.customer_code
    ):
        raise _Ignore("membership_scope_mismatch")
    if membership.paystack_subscription_code not in (None, "", subscription.code):
        raise _Ignore("not_current_subscription")
    payment = StudyPayment.objects.filter(
        user_id=membership.user_id, tier=membership.tier, mode=subscription.mode,
        plan=StudyMembership.Plan.MONTHLY, source=StudyPayment.Source.CHECKOUT,
        status=StudyPayment.Status.SUCCEEDED, verified_at__isnull=False,
        discarded_at__isnull=True,
        paystack_plan_code=subscription.plan_code,
    ).first()
    if payment is None:
        raise _Retry("checkout_not_verified")
    if subscription.mode == "live" and not membership.paystack_subscription_code and StudyPayment.objects.filter(
        user_id=membership.user_id, mode="live", source="checkout",
        paystack_plan_code=subscription.plan_code, discarded_at__isnull=False,
    ).exists() and payment.paystack_transaction_id not in subscription.invoice_transaction_ids:
        # A delayed subscription.create from a discarded same-tier checkout
        # must not be attached to the replacement's membership.
        raise _Retry("awaiting_exact_checkout_subscription_link")
    if not membership.paystack_subscription_code and (
        subscription.created_at is None
        or subscription.created_at < payment.created_at - timedelta(minutes=5)
        or subscription.created_at > timezone.now() + timedelta(minutes=5)
    ):
        raise _Retry("subscription_time_mismatch")


def _owner(subscription):
    linked = StudyMembership.objects.filter(paystack_subscription_code=subscription.code).first()
    if linked is not None:
        _proof(linked, subscription)
        return linked
    candidates = StudyMembership.objects.filter(
        payment_mode=subscription.mode, plan=StudyMembership.Plan.MONTHLY,
        paystack_customer_code=subscription.customer_code,
    ).filter(Q(paystack_subscription_code__isnull=True) | Q(paystack_subscription_code=""))
    matched = []
    wait_reason = "checkout_not_verified"
    for membership in candidates:
        try:
            _proof(membership, subscription)
        except _Retry as outcome:
            wait_reason = str(outcome)
            continue
        matched.append(membership)
    if len(matched) > 1:
        raise _Retry("ambiguous_membership")
    if not matched:
        if not candidates.exists() and StudyMembership.objects.filter(
            payment_mode=subscription.mode,
            paystack_customer_code=subscription.customer_code,
        ).exists():
            raise _Ignore("not_current_subscription")
        raise _Retry(wait_reason)
    return matched[0]


def _apply(receipt_id, membership, subscription):
    with transaction.atomic():
        # Match the user-first lock order used by checkout and cancellation.
        get_user_model().objects.select_for_update().get(pk=membership.user_id)
        receipt = PaystackWebhookReceipt.objects.select_for_update().get(pk=receipt_id)
        if not _due(receipt):
            return receipt
        current = StudyMembership.objects.select_for_update().get(pk=membership.pk)
        _proof(current, subscription)
        fields = []
        if current.paystack_subscription_code != subscription.code:
            current.paystack_subscription_code = subscription.code
            fields.append("paystack_subscription_code")
        result = "subscription_linked"
        if subscription.status in STOPPED_STATUSES:
            current.status = (
                StudyMembership.Status.NON_RENEWING
                if current.paid_until and current.paid_until > timezone.now()
                else StudyMembership.Status.EXPIRED
            )
            current.grace_until = None
            fields.extend(["status", "grace_until"])
            result = "renewals_stopped"
        # Active/attention metadata is not a successful payment. Never extend
        # access, clear payment-failure state, or undo local cancellation here.
        if fields:
            current.save(update_fields=[*fields, "updated_at"])
        return _finish_locked(receipt, State.PROCESSED, result)


def process_test_subscription_receipt(receipt_id):
    return _process_subscription_receipt(receipt_id, PaystackTestClient(), "test")


def process_live_subscription_receipt(receipt_id):
    return _process_subscription_receipt(receipt_id, PaystackLiveClient(), "live")


def _process_subscription_receipt(receipt_id, client, mode):
    if not _positive_id(receipt_id):
        raise ValueError("A valid stored receipt ID is required.")
    receipt = PaystackWebhookReceipt.objects.filter(
        pk=receipt_id, mode=mode, event_type__in=SUBSCRIPTION_EVENTS,
    ).first()
    if receipt is None:
        raise ValueError("Only stored test subscription notifications can be processed here.")
    if not _due(receipt):
        return receipt
    try:
        subscription = _canonical_subscription(client, receipt.snapshot)
        return _apply(receipt.pk, _owner(subscription), subscription)
    except _Ignore as outcome:
        return _finish(receipt.pk, State.IGNORED, str(outcome))
    except _Retry as outcome:
        return _finish(receipt.pk, State.RETRY, str(outcome))
    except PaystackError:
        return _finish(receipt.pk, State.RETRY, "provider_unavailable")
    except IntegrityError:
        return _finish(receipt.pk, State.RETRY, "subscription_link_conflict")
    except (StudyMembership.DoesNotExist, get_user_model().DoesNotExist):
        return _finish(receipt.pk, State.RETRY, "membership_not_ready")

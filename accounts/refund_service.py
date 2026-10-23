"""Automatic first-payment guarantee. No real refund is made by a browser view.

An owned, provider-verified first purchase requested within seven days needs no
manual approval. Persist intent BEFORE the financial POST; after an ambiguous
response only GET reconciliation is allowed. Never submit another refund blindly.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import StudyMembership, StudyPayment, StudyRefund
from .payment_service import CheckoutNotAllowed
from .paystack_checkout import _positive_integer, _validate_transaction
from .paystack_client import PaystackError, PaystackLiveClient, live_billing_enabled
from .subscription_service import _cancel_membership


Status = StudyRefund.Status
TERMINAL = {Status.COMPLETED, Status.INELIGIBLE}


class RefundNotAllowed(ValueError):
    pass


class _Attention(Exception):
    """Internal constant only; never copy a provider message into records."""


def refunds_enabled():
    return bool(live_billing_enabled() and getattr(settings, "PAYSTACK_LIVE_REFUNDS_ENABLED", False))


def _first_payment(user_id):
    return StudyPayment.objects.filter(
        user_id=user_id, mode="live", source="checkout", status__in=("succeeded", "reversed"),
        verified_at__isnull=False, paystack_transaction_id__isnull=False,
        discarded_at__isnull=True,
    ).order_by("created_at", "pk").first()


def refund_page_context(request):
    if not request.user.is_authenticated:
        return {}
    refund = StudyRefund.objects.filter(user=request.user, mode="live", reason="first_payment").first()
    enabled = refunds_enabled() and request.is_secure() and request.get_host().lower() == "studigarden.com"
    payment = _first_payment(request.user.pk) if enabled and not refund else None
    member = StudyMembership.objects.filter(user=request.user, payment_mode="live").first()
    return {
        "refund_request": refund,
        "can_request_refund": bool(payment and payment.status == "succeeded" and member and member.tier == payment.tier
                                   and not payment.refund_requests.exclude(status="ineligible").exists()),
        "upgrade_refunds": StudyRefund.objects.filter(user=request.user, mode="live", reason="upgrade").select_related("payment"),
        "discarded_checkout_refunds": StudyRefund.objects.filter(
            user=request.user, mode="live", reason="discarded_checkout",
        ).select_related("payment"),
    }


def request_first_payment_refund(user):
    received_at = timezone.now()
    if not refunds_enabled():
        raise RefundNotAllowed("Automatic refund requests are not available right now.")
    if not user or not user.is_authenticated or not user.is_active or not user.pk:
        raise RefundNotAllowed("Sign in to the account that made the purchase.")
    with transaction.atomic():
        locked = get_user_model().objects.select_for_update().get(pk=user.pk)
        if not locked.is_active:
            raise RefundNotAllowed("An active account is required to submit a request here.")
        existing = StudyRefund.objects.filter(user=locked, reason="first_payment").first()
        if existing:
            return existing
        payment = _first_payment(locked.pk)
        if not payment or payment.status != "succeeded" or payment.plan != "monthly":
            raise RefundNotAllowed("There is no verified first paid purchase eligible for this refund button.")
        member = StudyMembership.objects.filter(user=locked, payment_mode="live").first()
        if not member or member.tier != payment.tier or payment.refund_requests.exclude(status="ineligible").exists():
            raise RefundNotAllowed("This first payment has already been replaced or is being refunded. Check your Profile for its status.")
        # No amount, payment ID, timestamp or approval flag comes from the form.
        return StudyRefund.objects.create(
            user=locked, payment=payment, mode="live",
            amount_cents=payment.expected_amount_cents, currency=payment.currency, requested_at=received_at,
        )


def _due(refund):
    return refund.status not in TERMINAL and not (
        refund.status == Status.ATTENTION and refund.paystack_refund_id is None
    ) and (refund.next_attempt_at is None or refund.next_attempt_at <= timezone.now())


def _locked(refund):
    get_user_model().objects.select_for_update().get(pk=refund.user_id)
    return StudyRefund.objects.select_for_update().select_related("payment", "user").get(pk=refund.pk)


def _scope(refund):
    payment = refund.payment
    first = _first_payment(refund.user_id)
    if not (
        refund.mode == payment.mode == "live" and payment.user_id == refund.user_id
        and (payment.source == "checkout" or (refund.reason == "upgrade" and payment.source == "renewal"))
        and payment.plan == "monthly"
        and payment.status in {"succeeded", "reversed"}
        and payment.verified_at
        and _positive_integer(payment.paystack_transaction_id)
        and refund.amount_cents == payment.expected_amount_cents
        and refund.currency == payment.currency == "ZAR"
    ):
        raise _Attention("payment_scope_changed")
    if refund.reason == StudyRefund.Reason.UPGRADE:
        from .upgrade_service import UpgradeAttention, upgrade_refund_change
        try:
            upgrade_refund_change(refund)
        except UpgradeAttention as exc:
            raise _Attention(str(exc)) from None
    elif refund.reason == StudyRefund.Reason.DISCARDED_CHECKOUT:
        if not payment.discarded_at:
            raise _Attention("checkout_not_discarded")
    elif refund.reason != StudyRefund.Reason.FIRST_PAYMENT or not first or first.pk != payment.pk or payment.discarded_at:
        raise _Attention("payment_scope_changed")
    return payment


def _defer(refund, code, *, attention=False):
    with transaction.atomic():
        refund = _locked(refund)
        if refund.status in TERMINAL:
            return refund
        if attention:
            refund.status = Status.ATTENTION
        refund.attempt_count = min(refund.attempt_count + 1, 2_147_483_647)
        refund.last_result = code
        refund.next_attempt_at = timezone.now() + timedelta(
            seconds=min(60 * 2 ** min(refund.attempt_count - 1, 6), 3600),
        )
        refund.save(update_fields=["status", "last_result", "next_attempt_at", "attempt_count", "updated_at"])
        return refund


def _assess(client, refund):
    payment = _scope(refund)
    result = client.verify(payment.reference)
    paid_at = _validate_transaction(result, payment)
    member = StudyMembership.objects.filter(user_id=refund.user_id, payment_mode="live").first()
    discarded = refund.reason == StudyRefund.Reason.DISCARDED_CHECKOUT
    upgrade = refund.reason == StudyRefund.Reason.UPGRADE
    if upgrade:
        from .upgrade_service import UpgradeAttention, upgrade_refund_change, validate_upgrade_credit
        try:
            if not validate_upgrade_credit(client, upgrade_refund_change(refund)):
                raise _Attention("upgrade_not_in_current_paid_period")
        except UpgradeAttention as exc:
            raise _Attention(str(exc)) from None
    if not (
        result.get("status") == "success" and result.get("id") == payment.paystack_transaction_id
        and paid_at and (discarded or upgrade or (
            member and member.tier == payment.tier
            and member.paystack_customer_code == result["customer"]["customer_code"]
        ))
    ):
        raise _Attention("transaction_not_refundable")
    with transaction.atomic():
        refund = _locked(refund)
        if refund.status != Status.REQUESTED:
            return refund
        _scope(refund)
        refund.paid_at = paid_at
        # Use the server-recorded request time, NOT processing time. A request
        # arriving before the deadline stays eligible through outages or queues.
        if not (discarded or upgrade) and not paid_at <= refund.requested_at <= paid_at + timedelta(days=7):
            refund.status = Status.INELIGIBLE
            refund.last_result = "outside_seven_day_guarantee"
        else:
            refund.status = Status.APPROVED
            refund.approved_at = timezone.now()
            refund.last_result = "approved_automatically"
        refund.next_attempt_at = None
        refund.save(update_fields=["status", "paid_at", "approved_at", "last_result", "next_attempt_at", "updated_at"])
        return refund


def _validate_refund(result, payment):
    if not isinstance(result, dict):
        raise _Attention("refund_shape_invalid")
    related = result.get("transaction")
    transaction_id = related.get("id") if isinstance(related, dict) else related
    if not (
        result.get("domain") == "live" and _positive_integer(result.get("id"))
        and type(result.get("amount")) is int and result["amount"] == payment.expected_amount_cents
        and result.get("currency") == payment.currency == "ZAR"
        and type(transaction_id) is int and transaction_id == payment.paystack_transaction_id
        and (not isinstance(related, dict) or (
            related.get("domain") in (None, "live")
            and related.get("reference", payment.reference) == payment.reference
        ))
        and result.get("status") in {"pending", "processing", "processed", "failed", "needs-attention"}
    ):
        raise _Attention("refund_ownership_or_amount_mismatch")
    return result


def _apply(refund, result):
    with transaction.atomic():
        refund = _locked(refund)
        if refund.status in TERMINAL:
            return refund
        payment = _scope(refund)
        _validate_refund(result, payment)
        if (refund.paystack_refund_id not in (None, result["id"])
                or StudyRefund.objects.filter(mode="live", paystack_refund_id=result["id"]).exclude(pk=refund.pk).exists()):
            raise _Attention("refund_identifier_conflict")
        refund.paystack_refund_id = result["id"]
        refund.attempt_count = min(refund.attempt_count + 1, 2_147_483_647)
        provider_status = result["status"]
        if provider_status == "processed":
            refund.status = Status.COMPLETED
            refund.completed_at = timezone.now()
            refund.next_attempt_at = None
            refund.last_result = "refund_completed"
            StudyPayment.objects.filter(pk=payment.pk).update(status="reversed", updated_at=timezone.now())
            member = StudyMembership.objects.select_for_update().filter(user_id=refund.user_id).first()
            other_paid = StudyPayment.objects.filter(
                user_id=refund.user_id, mode="live", status="succeeded", verified_at__isnull=False,
                discarded_at__isnull=True,
            ).exclude(pk=payment.pk).exists()
            if (refund.reason == StudyRefund.Reason.FIRST_PAYMENT
                    and member and member.payment_mode == "live" and member.tier == payment.tier
                    and member.paystack_subscription_code == refund.cancelled_subscription_code and not other_paid):
                member.status = "expired"
                member.paid_until = min(member.paid_until, timezone.now()) if member.paid_until else timezone.now()
                member.grace_until = None
                member.save(update_fields=["status", "paid_until", "grace_until", "updated_at"])
            # Never alter beta/admin privileges or delete study data. Do not
            # revoke a newer entitlement funded by a different successful charge.
        elif provider_status in {"failed", "needs-attention"}:
            refund.status = Status.ATTENTION
            refund.last_result = "refund_failed" if provider_status == "failed" else "bank_details_required"
            refund.next_attempt_at = timezone.now() + timedelta(hours=1)
        else:
            refund.status = Status.PROCESSING
            refund.last_result = "refund_processing"
            refund.next_attempt_at = timezone.now() + timedelta(minutes=2)
        refund.save()
        return refund


def _find_existing(client, refund):
    records = client.list_refunds(refund.payment.paystack_transaction_id)
    # Never guess between partial refunds or trust that a provider applied a
    # query filter. Validate every returned item's exact transaction ownership.
    if not records:
        return None
    if len(records) != 1:
        raise _Attention("existing_refunds_require_attention")
    listed = _validate_refund(records[0], refund.payment)
    canonical = client.fetch_refund(listed["id"])
    _validate_refund(canonical, refund.payment)
    if canonical["id"] != listed["id"]:
        raise _Attention("refund_identifier_conflict")
    return canonical


def process_live_refund(refund_id):
    client = PaystackLiveClient()
    refund = StudyRefund.objects.select_related("payment", "user").filter(pk=refund_id, mode="live").first()
    if refund is None:
        raise ValueError("A stored LIVE refund request is required.")
    if not _due(refund):
        return refund
    try:
        _scope(refund)
        if refund.status == Status.REQUESTED:
            refund = _assess(client, refund)
        if refund.status in TERMINAL:
            return refund
        if refund.status == Status.APPROVED:
            # A later account deactivation does not invalidate an accepted money
            # return request. Only this approved workflow permits inactive users.
            if refund.reason == StudyRefund.Reason.DISCARDED_CHECKOUT:
                from .discarded_checkouts import cancel_discarded_subscription
                cancelled_code = cancel_discarded_subscription(client, refund)
            elif refund.reason == StudyRefund.Reason.UPGRADE:
                from .upgrade_service import UpgradeAttention, stop_previous_upgrade_subscription, upgrade_refund_change
                try:
                    cancelled_code = stop_previous_upgrade_subscription(client, upgrade_refund_change(refund))
                except UpgradeAttention as exc:
                    raise _Attention(str(exc)) from None
            else:
                member = _cancel_membership(user=refund.user, client=client, mode="live", allow_inactive=True)
                cancelled_code = member.paystack_subscription_code
            with transaction.atomic():
                refund = _locked(refund)
                if refund.status != Status.APPROVED:
                    return refund
                refund.cancelled_subscription_code = cancelled_code
                refund.save(update_fields=["cancelled_subscription_code", "updated_at"])
            existing = _find_existing(client, refund)
            if existing:
                return _apply(refund, existing)
            with transaction.atomic():
                refund = _locked(refund)
                _scope(refund)
                if refund.status != Status.APPROVED:
                    return refund
                refund.status = Status.SUBMITTING
                refund.submitted_at = timezone.now()
                refund.last_result = "refund_submission_started"
                refund.next_attempt_at = timezone.now() + timedelta(minutes=2)
                refund.save(update_fields=["status", "submitted_at", "last_result", "next_attempt_at", "updated_at"])
            # The intent is durably committed. NO automatic path repeats this
            # POST after a crash/timeout, even if a later GET returns no refund.
            if refund.reason == StudyRefund.Reason.DISCARDED_CHECKOUT:
                result = client.create_full_refund(
                    refund.payment.paystack_transaction_id, refund.amount_cents,
                    f"StudiGarden discarded checkout refund {refund.pk}",
                    customer_note="Refund for a replaced StudiGarden checkout; your chosen plan is unchanged.",
                )
            elif refund.reason == StudyRefund.Reason.UPGRADE:
                result = client.create_full_refund(
                    refund.payment.paystack_transaction_id, refund.amount_cents,
                    f"StudiGarden upgrade credit {refund.pk}",
                    customer_note="Refund of the lower plan's payment for the billing period replaced by your StudiGarden upgrade. Your upgraded plan is unchanged.",
                )
            else:
                result = client.create_full_refund(
                    refund.payment.paystack_transaction_id, refund.amount_cents, f"StudiGarden guarantee request {refund.pk}",
                )
            _validate_refund(result, refund.payment)
            return _apply(refund, result)
        if refund.paystack_refund_id is not None:
            result = client.fetch_refund(refund.paystack_refund_id)
            if result.get("id") != refund.paystack_refund_id:
                raise _Attention("refund_identifier_conflict")
            return _apply(refund, result)
        if refund.status == Status.SUBMITTING:
            existing = _find_existing(client, refund)
            if existing:
                return _apply(refund, existing)
            if refund.submitted_at and refund.submitted_at < timezone.now() - timedelta(hours=24):
                return _defer(refund, "submission_unconfirmed", attention=True)
            return _defer(refund, "waiting_for_provider_refund")
        return refund
    except _Attention as exc:
        if refund.status == Status.SUBMITTING and refund.paystack_refund_id is None:
            if refund.submitted_at and refund.submitted_at < timezone.now() - timedelta(hours=24):
                return _defer(refund, "submission_unconfirmed", attention=True)
            return _defer(refund, "submission_confirmation_pending")
        return _defer(refund, str(exc), attention=True)
    except (PaystackError, CheckoutNotAllowed):
        if (refund.reason in {StudyRefund.Reason.DISCARDED_CHECKOUT, StudyRefund.Reason.UPGRADE}
                and refund.status in {Status.REQUESTED, Status.APPROVED}
                and refund.requested_at < timezone.now() - timedelta(hours=24)):
            code = ("upgrade_refund_needs_attention" if refund.reason == StudyRefund.Reason.UPGRADE
                    else "discarded_subscription_needs_attention")
            return _defer(refund, code, attention=True)
        return _defer(refund, "provider_confirmation_pending")
    except IntegrityError:
        return _defer(refund, "refund_identity_conflict", attention=True)


def process_refund_batch(limit=5):
    # Continue already accepted requests even when NEW requests are paused.
    if not live_billing_enabled():
        raise RefundNotAllowed("Live billing is disabled.")
    due = StudyRefund.objects.filter(mode="live").exclude(status__in=TERMINAL).exclude(
        status=Status.ATTENTION, paystack_refund_id__isnull=True,
    ).filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()))
    outcomes = []
    for refund_id in list(due.order_by("requested_at", "pk").values_list("pk", flat=True)[:limit]):
        try:
            refund = process_live_refund(refund_id)
        except DatabaseError:
            raise
        except Exception:
            refund = StudyRefund.objects.get(pk=refund_id)
            refund = _defer(refund, "refund_processor_error", attention=refund.status != Status.SUBMITTING)
        outcomes.append((refund.pk, refund.status, refund.last_result))
    return outcomes

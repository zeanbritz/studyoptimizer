"""Resume an exact stopped renewal, or restart through a new verified checkout.

Historical/refunded payments prove ownership only, never new access. Provider
intent commits before checkout/enable requests; cancellation uses the same lock.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .access import has_permanent_free_access
from .downgrade_cancellation import _resume_old, stop_change_subscription
from .downgrade_service import ScheduleAttention, _funding_payment
from .membership_proof import membership_payment
from .models import StudyMembership, StudyPayment, StudyPlanChange, StudyRefund
from .payment_service import CheckoutNotAllowed, create_checkout_attempt
from .paystack_checkout import _one_month_after, _validate_plan, _validate_transaction
from .paystack_client import PaystackError, PaystackLiveClient, live_billing_enabled, live_callback_url, valid_authorization_url
from .plan_changes import OPEN_CHANGE_STATES, quote_plan_change, validate_quote_snapshot
from .subscription_service import _find_subscription, RENEWING_STATUSES, STOPPED_STATUSES
from .upgrade_service import _period


def _pending_refund(user_id):
    return StudyRefund.objects.filter(user_id=user_id, mode="live").exclude(status__in=("completed", "ineligible")).exists()


def _owned_history(client, member, *, restart=False):
    if restart:
        initial = membership_payment(member, allow_refunded_history=True)
        if initial is None:
            raise CheckoutNotAllowed("The previous subscription's payment ownership must be verified first.")
        funding = StudyPayment.objects.filter(
            user_id=member.user_id, mode="live", tier=member.tier, plan="monthly", status__in=("succeeded", "reversed"),
            period_end=member.paid_until, paystack_plan_code=initial.paystack_plan_code,
            verified_at__isnull=False, paystack_transaction_id__isnull=False, discarded_at__isnull=True,
        ).first() or initial
    else:
        initial, funding = _funding_payment(member)
    sub = _find_subscription(client, member, initial)
    code = sub["subscription_code"]
    if (sub.get("status") not in RENEWING_STATUSES | STOPPED_STATUSES
            or StudyMembership.objects.filter(paystack_subscription_code=code).exclude(pk=member.pk).exists()
            or funding.paystack_subscription_code not in ("", code)
            or (funding.source == "renewal" and funding.paystack_subscription_code != code)):
        raise CheckoutNotAllowed("The previous subscription could not be matched safely.")
    result = client.verify(funding.reference)
    paid_at = _validate_transaction(result, funding)
    if (result.get("status") != "success" or not paid_at or result.get("id") != funding.paystack_transaction_id
            or result["customer"]["customer_code"] != member.paystack_customer_code):
        raise CheckoutNotAllowed("The previous payment could not be verified.")
    start, end = _period(funding, paid_at)
    refunded = funding.status == "reversed" and funding.refund_requests.filter(status="completed").exists()
    if funding.status != "succeeded" and not (restart and refunded):
        raise CheckoutNotAllowed("The previous payment's refund status is not confirmed.")
    if not restart and (end != member.paid_until or not start <= timezone.now() < end
                        or funding.refund_requests.exclude(status="ineligible").exists()):
        raise CheckoutNotAllowed("There is no confirmed funded month to resume.")
    if restart:
        # A new renewal may have reached Paystack before its notification. Do not
        # charge a fresh month over an already-paid but unrecorded current month.
        invoice = sub.get("most_recent_invoice")
        if isinstance(invoice, dict) and invoice.get("paid") in (True, 1) and invoice.get("status") == "success":
            try:
                invoice_end = parse_datetime(invoice.get("period_end", ""))
            except (TypeError, ValueError):
                invoice_end = None
            if invoice_end and timezone.is_aware(invoice_end) and invoice_end > timezone.now():
                if invoice.get("transaction") != funding.paystack_transaction_id or not refunded:
                    raise CheckoutNotAllowed("A recent renewal must be reconciled before starting another payment.")
        if end > timezone.now() and not refunded:
            raise CheckoutNotAllowed("The previous funded period has not ended. Refresh your current plan first.")
    return initial, funding, sub


def _scope(change, member):
    previous = change.previous_payment
    if not (change.kind in {"resume", "restart"} and member.user_id == previous.user_id == change.user_id
            and member.payment_mode == previous.mode == "live" and member.plan == previous.plan == "monthly"
            and member.tier == previous.tier == change.from_tier
            and member.paystack_customer_code == change.customer_code
            and member.paystack_subscription_code in (None, "", change.from_subscription_code)
            and member.paid_until == change.from_paid_until
            and previous.paystack_plan_code == change.from_plan_code
            and previous.paystack_subscription_code == change.from_subscription_code
            and previous.verified_at and previous.paystack_transaction_id and not previous.discarded_at
            and previous.status in {"succeeded", "reversed"} and change.currency == previous.currency == "ZAR"):
        raise ScheduleAttention("reactivation_scope_changed")
    if StudyMembership.objects.filter(paystack_subscription_code=change.from_subscription_code).exclude(pk=member.pk).exists():
        raise ScheduleAttention("reactivation_subscription_owned_elsewhere")


def _request(*, user, tier, kind, expected_quote=None):
    quote = quote_plan_change(user=user, tier=tier)
    if quote.kind != kind:
        raise CheckoutNotAllowed("Your plan has changed. Review the current billing options before continuing.")
    client = PaystackLiveClient()
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        quote = quote_plan_change(user=user, tier=tier)
        validate_quote_snapshot(user, quote, expected_quote)
        if quote.kind != kind or _pending_refund(user.pk):
            raise CheckoutNotAllowed("Finish the current payment or refund before resuming or restarting a plan.")
        existing = StudyPlanChange.objects.filter(user=user, state__in=OPEN_CHANGE_STATES).first()
        if existing:
            if existing.kind == kind and existing.to_tier == tier and not existing.cancel_requested:
                return existing
            raise CheckoutNotAllowed("A plan change is already being handled. Check Profile first.")
        if StudyPayment.objects.filter(user=user, mode="live", source="checkout", discarded_at__isnull=True).exclude(
            status__in=("succeeded", "reversed"),
        ).exists():
            raise CheckoutNotAllowed("Check the previous unfinished payment before starting another billing instruction.")
        member = StudyMembership.objects.select_for_update().get(user=user)
        initial, funding, sub = _owned_history(client, member, restart=kind == "restart")
        funding.paystack_subscription_code = sub["subscription_code"]
        funding.save(update_fields=["paystack_subscription_code", "updated_at"])
        payment = create_checkout_attempt(user=user, tier=tier, mode="live") if kind == "restart" else None
        return StudyPlanChange.objects.create(
            user=user, kind=kind, state="checkout" if payment else "queued", from_tier=member.tier, to_tier=tier,
            from_subscription_code=sub["subscription_code"], from_plan_code=initial.paystack_plan_code,
            to_plan_code=payment.paystack_plan_code if payment else initial.paystack_plan_code,
            amount_due_now_cents=quote.amount_due_now_cents, monthly_amount_cents=quote.next_monthly_amount_cents,
            customer_code=member.paystack_customer_code, billing_email=funding.checkout_email,
            from_paid_until=member.paid_until, effective_at=quote.effective_at,
            payment=payment, previous_payment=funding,
        )


def request_live_resume(*, user, tier, expected_quote=None):
    return _request(user=user, tier=tier, kind="resume", expected_quote=expected_quote)


def prepare_live_restart(*, user, tier, expected_quote=None):
    change = _request(user=user, tier=tier, kind="restart", expected_quote=expected_quote)
    client = PaystackLiveClient()
    # The reference/intent is already durable if initialize times out. Never
    # create a subscription here: the plan checkout already creates it.
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        quote = quote_plan_change(user=user, tier=tier)
        if quote.kind != "restart" or _pending_refund(user.pk):
            raise CheckoutNotAllowed("The restart is no longer ready. Check Profile before another payment.")
        change = StudyPlanChange.objects.select_for_update().select_related("previous_payment").get(pk=change.pk)
        payment = StudyPayment.objects.select_for_update().get(pk=change.payment_id)
        member = StudyMembership.objects.select_for_update().get(user=user)
        _scope(change, member)
        if change.state != "checkout" or change.cancel_requested or payment.discarded_at:
            raise CheckoutNotAllowed("This restart was cancelled or changed in another tab.")
        if change.to_plan_code != payment.paystack_plan_code or payment.expected_amount_cents != quote.amount_due_now_cents:
            raise CheckoutNotAllowed("The restart price changed. Contact support before continuing.")
        stop_change_subscription(client, change, change.from_subscription_code)
        change.old_stopped_at = change.old_stopped_at or timezone.now()
        change.save(update_fields=["old_stopped_at", "updated_at"])
    # Preserve the confirmed stop even if checkout initialization times out.
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        quote = quote_plan_change(user=user, tier=tier)
        change = StudyPlanChange.objects.select_for_update().select_related("previous_payment").get(pk=change.pk)
        member = StudyMembership.objects.select_for_update().get(user=user)
        payment = StudyPayment.objects.select_for_update().get(pk=change.payment_id)
        _scope(change, member)
        if (quote.kind != "restart" or change.state != "checkout" or change.cancel_requested
                or not change.old_stopped_at or payment.discarded_at or _pending_refund(user.pk)):
            raise CheckoutNotAllowed("This restart changed before checkout. Review your Profile first.")
        if payment.status in {"pending", "failed", "abandoned"} and valid_authorization_url(payment.authorization_url):
            return payment
        if payment.status != "created":
            raise CheckoutNotAllowed("Check this restart payment's status before continuing.")
        _validate_plan(client.fetch_plan(payment.paystack_plan_code), payment)
        result = client.initialize({
            "email": payment.checkout_email, "amount": payment.expected_amount_cents, "currency": payment.currency,
            "reference": payment.reference, "plan": payment.paystack_plan_code, "channels": ["card"],
            "callback_url": live_callback_url(), "metadata": {"studigarden_reference": payment.reference, "tier": payment.tier},
        })
        if result.get("reference") != payment.reference or not valid_authorization_url(result.get("authorization_url")):
            raise PaystackError("Restart checkout needs confirmation. Check payment status before trying again.")
        payment.status, payment.authorization_url = "pending", result["authorization_url"]
        payment.save(update_fields=["status", "authorization_url", "updated_at"])
        return payment


def record_verified_restart(user, payment, result, paid_at, change):
    """Normal checkout verifies price/mode/TX before entering this user lock."""
    change = StudyPlanChange.objects.select_for_update().select_related("previous_payment").get(pk=change.pk)
    if not (change.kind == "restart" and change.user_id == payment.user_id == user.pk and change.payment_id == payment.pk
            and payment.mode == "live" and payment.source == "checkout" and payment.plan == "monthly"
            and payment.tier == change.to_tier and payment.currency == change.currency == "ZAR"
            and payment.paystack_plan_code == change.to_plan_code
            and payment.expected_amount_cents == change.amount_due_now_cents == change.monthly_amount_cents):
        raise PaystackError("The restart payment does not match its saved instruction.")
    member = StudyMembership.objects.select_for_update().get(user=user)
    conflict = (change.state != "checkout" or change.cancel_requested or not change.old_stopped_at
                or not user.is_active or has_permanent_free_access(user) or _pending_refund(user.pk)
                or paid_at < change.requested_at - timedelta(minutes=5)
                or (member.paid_until and member.paid_until > timezone.now() and member.status != "expired"))
    try:
        _scope(change, member)
    except ScheduleAttention:
        conflict = True
    payment.status, payment.paystack_transaction_id, payment.verified_at = "succeeded", result["id"], timezone.now()
    payment.period_start, payment.period_end = paid_at, _one_month_after(paid_at)
    if conflict:
        payment.discarded_at = timezone.now()
        StudyRefund.objects.get_or_create(payment=payment, reason="discarded_checkout", defaults={
            "user": user, "mode": "live", "amount_cents": payment.expected_amount_cents, "currency": "ZAR",
        })
        change.state, change.last_result = "cancelled", "restart_conflict_refund_queued"
    else:
        member.tier, member.status = payment.tier, "active" if payment.period_end > timezone.now() else "expired"
        member.paid_until, member.grace_until = payment.period_end, None
        member.paystack_customer_code, member.paystack_subscription_code = result["customer"]["customer_code"], None
        member.save(update_fields=["tier", "status", "paid_until", "grace_until", "paystack_customer_code", "paystack_subscription_code", "updated_at"])
        change.state, change.last_result, change.applied_at = "applied", "restart_payment_verified", timezone.now()
        change.effective_at = paid_at
    payment.save(update_fields=["status", "paystack_transaction_id", "verified_at", "period_start", "period_end", "discarded_at", "updated_at"])
    change.next_attempt_at = None
    change.save()
    return payment


def request_reactivation_cancellation(*, user):
    """Normal cancellation/refunds also retire pending enable/restart instructions."""
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        change = StudyPlanChange.objects.select_for_update().filter(
            user=user, kind__in=("resume", "restart"), state__in=OPEN_CHANGE_STATES,
        ).first()
        if not change:
            return None
        change.cancel_requested, change.restore_current = True, False
        change.cancel_requested_at = change.cancel_requested_at or timezone.now()
        change.state, change.next_attempt_at, change.last_result = "queued", None, "reactivation_cancel_requested"
        if change.payment_id:
            payment = StudyPayment.objects.select_for_update().get(pk=change.payment_id)
            payment.discarded_at = payment.discarded_at or timezone.now()
            payment.save(update_fields=["discarded_at", "updated_at"])
        change.save()
        return change


def _defer(change_id, code, *, attention=False):
    with transaction.atomic():
        owner = StudyPlanChange.objects.values_list("user_id", flat=True).get(pk=change_id)
        get_user_model().objects.select_for_update().get(pk=owner)
        change = StudyPlanChange.objects.select_for_update().get(pk=change_id)
        if change.state not in {"queued", "submitting"}:
            return change
        change.attempt_count = min(change.attempt_count + 1, 2_147_483_647)
        change.state = "attention" if attention else change.state
        change.last_result = code
        change.next_attempt_at = timezone.now() + timedelta(seconds=min(60 * 2 ** min(change.attempt_count - 1, 6), 3600))
        change.save(update_fields=["attempt_count", "state", "last_result", "next_attempt_at", "updated_at"])
        return change


def process_reactivation_change(change_id):
    client = PaystackLiveClient()
    change = StudyPlanChange.objects.get(pk=change_id, kind__in=("resume", "restart"))
    if change.state not in {"queued", "submitting"} or (change.next_attempt_at and change.next_attempt_at > timezone.now()):
        return change
    try:
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=change.user_id)
            change = StudyPlanChange.objects.select_for_update().select_related("previous_payment").get(pk=change.pk)
            member = StudyMembership.objects.select_for_update().get(user=user)
            if change.state not in {"queued", "submitting"}:
                return change
            refund_pending = _pending_refund(user.pk)
            if change.cancel_requested or not user.is_active or has_permanent_free_access(user):
                stop_change_subscription(client, change, change.from_subscription_code)
                change.cancel_requested = True
                change.cancel_requested_at = change.cancel_requested_at or timezone.now()
                change.old_stopped_at = change.old_stopped_at or timezone.now()
                if (member.paystack_subscription_code in (None, "", change.from_subscription_code)
                        and member.tier == change.from_tier and member.paystack_customer_code == change.customer_code
                        and member.paid_until == change.from_paid_until):
                    member.status, member.grace_until = "non_renewing", None
                    member.save(update_fields=["status", "grace_until", "updated_at"])
                change.state, change.last_result, change.cancelled_at = "cancelled", "reactivation_billing_stopped", timezone.now()
                change.next_attempt_at = None
                change.save()
                return change
            if refund_pending:
                return _defer(change.pk, "refund_confirmation_pending")
            _scope(change, member)
            if change.kind != "resume":
                raise ScheduleAttention("restart_needs_checkout_confirmation")
            if member.paid_until <= timezone.now():
                # Never re-enable an expired schedule that could charge at once.
                change.cancel_requested, change.cancel_requested_at = True, timezone.now()
                change.save(update_fields=["cancel_requested", "cancel_requested_at", "updated_at"])
                stop_change_subscription(client, change, change.from_subscription_code)
                change.old_stopped_at, change.cancelled_at = timezone.now(), timezone.now()
                change.state, change.last_result = "cancelled", "resume_period_ended"
                change.save()
                return change
            if change.state == "queued":
                change.state, change.subscription_posted_at = "submitting", timezone.now()
                change.save(update_fields=["state", "subscription_posted_at", "updated_at"])
        # Durable enable intent precedes the provider mutation. GET confirms the
        # exact same subscription after timeouts, rather than creating a new one.
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=change.user_id)
            change = StudyPlanChange.objects.select_for_update().select_related("previous_payment").get(pk=change.pk)
            member = StudyMembership.objects.select_for_update().get(user=user)
            if change.state != "submitting" or change.cancel_requested:
                return change
            _scope(change, member)
            if (not user.is_active or has_permanent_free_access(user) or member.paid_until <= timezone.now()
                    or change.previous_payment.status != "succeeded" or change.previous_payment.discarded_at):
                change.cancel_requested, change.cancel_requested_at = True, timezone.now()
                change.state, change.next_attempt_at, change.last_result = "queued", None, "resume_cleanup_required"
                change.save()
                return change
            if _pending_refund(user.pk):
                return _defer(change.pk, "refund_confirmation_pending")
            _resume_old(client, change, member, user)
            change.state, change.last_result, change.applied_at = "applied", "renewals_resumed", timezone.now()
            change.next_attempt_at = None
            change.save(update_fields=["state", "last_result", "applied_at", "next_attempt_at", "updated_at"])
            return change
    except ScheduleAttention as exc:
        if change.kind == "resume" and change.subscription_posted_at and str(exc) in {
            "previous_plan_cannot_resume", "resume_price_unconfirmed", "resume_next_debit_unconfirmed", "resume_token_unconfirmed",
        }:
            # An enable may have succeeded before its follow-up GET failed. Do
            # not strand that possible renewal in an attention-only state.
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=change.user_id)
                change = StudyPlanChange.objects.select_for_update().get(pk=change.pk)
                if change.state == "submitting":
                    change.cancel_requested = True
                    change.cancel_requested_at = change.cancel_requested_at or change.subscription_posted_at
                    change.state, change.next_attempt_at, change.last_result = "queued", None, "resume_terms_cleanup_required"
                    change.save()
                    return change
        return _defer(change.pk, str(exc), attention=True)
    except PaystackError:
        return _defer(change.pk, "reactivation_provider_pending", attention=change.requested_at < timezone.now() - timedelta(hours=24))
    except IntegrityError:
        return _defer(change.pk, "reactivation_identity_conflict", attention=True)


def process_reactivation_batch(limit=5):
    if not live_billing_enabled():
        raise PaystackError("Live billing is disabled.")
    ids = StudyPlanChange.objects.filter(kind__in=("resume", "restart"), state__in=("queued", "submitting")).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()),
    ).order_by("requested_at", "pk").values_list("pk", flat=True)[:limit]
    outcomes = []
    for change_id in list(ids):
        try:
            change = process_reactivation_change(change_id)
        except DatabaseError:
            raise
        except Exception:
            change = _defer(change_id, "reactivation_processor_error", attention=True)
        outcomes.append((change.pk, change.state, change.last_result))
    return outcomes

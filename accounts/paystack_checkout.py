"""Local sandbox purchases only; renewal/webhook handling is a separate step."""

import calendar
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .access import get_study_tier, has_permanent_free_access
from .models import StudyMembership, StudyPayment, StudyTier
from .payment_service import CheckoutNotAllowed, create_test_checkout_attempt
from .paystack_client import (
    PaystackError, PaystackTestClient, checkout_callback_url,
    test_checkout_enabled, valid_authorization_url,
)


class PaymentNotFound(ValueError):
    pass


def checkout_page_context(request):
    """Public UI flags only; no keys or payment-provider calls."""
    enabled = test_checkout_enabled() and request.get_host().split(":", 1)[0].lower() in {
        "localhost", "127.0.0.1",
    }
    user = request.user
    can_start = bool(
        enabled and user.is_authenticated and user.is_active
        and get_study_tier(user) == StudyTier.FREE
        and not StudyPayment.objects.filter(
            user=user, mode=StudyPayment.Mode.TEST, status=StudyPayment.Status.SUCCEEDED,
        ).exists()
        and not StudyMembership.objects.filter(user=user).exclude(
            paystack_subscription_code__isnull=True,
        ).exclude(paystack_subscription_code="").exists()
    )
    pending = None
    test_membership = None
    can_cancel = False
    if enabled and user.is_authenticated:
        pending = StudyPayment.objects.filter(
            user=user, mode=StudyPayment.Mode.TEST, status=StudyPayment.Status.PENDING,
        ).first()
        test_membership = StudyMembership.objects.filter(
            user=user, payment_mode=StudyMembership.PaymentMode.TEST,
            plan=StudyMembership.Plan.MONTHLY,
        ).first()
        if test_membership and not (
            test_membership.status == StudyMembership.Status.NON_RENEWING
            and test_membership.paystack_subscription_code
        ):
            can_cancel = StudyPayment.objects.filter(
                user=user, tier=test_membership.tier, mode=StudyPayment.Mode.TEST,
                plan=StudyMembership.Plan.MONTHLY, source=StudyPayment.Source.CHECKOUT,
                status=StudyPayment.Status.SUCCEEDED, verified_at__isnull=False,
            ).exclude(paystack_plan_code="").exists()
    return {
        "test_checkout_enabled": enabled,
        "can_start_test_checkout": can_start,
        "pending_test_payment": pending,
        "can_cancel_test_membership": can_cancel,
        "test_renewals_cancelled": bool(
            test_membership and test_membership.status == StudyMembership.Status.NON_RENEWING
            and test_membership.paystack_subscription_code
        ),
        "test_paid_access_remaining": bool(
            test_membership and test_membership.paid_until and test_membership.paid_until > timezone.now()
        ),
    }


def _positive_integer(value):
    return type(value) is int and 0 < value <= 9_223_372_036_854_775_807


def _validate_plan(plan, payment):
    if not (
        plan.get("domain") == "test"
        and plan.get("plan_code") == payment.paystack_plan_code
        and type(plan.get("amount")) is int
        and plan["amount"] == payment.expected_amount_cents
        and plan.get("currency") == payment.currency
        and plan.get("interval") == "monthly"
        and not plan.get("is_deleted") and not plan.get("is_archived")
    ):
        raise PaystackError(
            "The Paystack test plan must match this tier's monthly ZAR price. "
            "No checkout was opened."
        )


def initialize_test_checkout(*, user, tier):
    client = PaystackTestClient()
    callback_url = checkout_callback_url()
    if not user or not user.is_authenticated or not user.is_active or not user.pk:
        raise CheckoutNotAllowed("An active account is required.")

    # Serializes double clicks, including requests choosing different tiers.
    # Network calls here have a strict timeout and are local-sandbox-only.
    with transaction.atomic():
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        if not locked_user.is_active or has_permanent_free_access(locked_user):
            raise CheckoutNotAllowed("This account cannot start paid checkout.")
        membership = StudyMembership.objects.filter(user=locked_user).first()
        if (
            get_study_tier(locked_user) in {StudyTier.GROW, StudyTier.BLOOM}
            or (membership and membership.paystack_subscription_code)
            or StudyPayment.objects.filter(
                user=locked_user, mode=StudyPayment.Mode.TEST,
                status=StudyPayment.Status.SUCCEEDED,
            ).exists()
        ):
            raise CheckoutNotAllowed(
                "This account already has a membership or verified test purchase. "
                "Use a separate local Free account to test another plan."
            )

        pending = StudyPayment.objects.filter(
            user=locked_user, mode=StudyPayment.Mode.TEST,
            source=StudyPayment.Source.CHECKOUT, status=StudyPayment.Status.PENDING,
        ).first()
        if pending:
            if pending.tier != tier:
                raise CheckoutNotAllowed(
                    "You already have a test checkout in progress for another plan. "
                    "Check its payment status on your Profile first."
                )
            if not valid_authorization_url(pending.authorization_url):
                raise PaystackError("This test checkout cannot be resumed. Check its status on your Profile.")
            return pending

        payment = create_test_checkout_attempt(user=locked_user, tier=tier)
        # A Paystack plan overrides the amount sent to initialize. Validate the
        # provider's plan BEFORE opening checkout, not just the local price.
        _validate_plan(client.fetch_plan(payment.paystack_plan_code), payment)
        result = client.initialize({
            "email": payment.checkout_email,
            "amount": payment.expected_amount_cents,
            "currency": payment.currency,
            "reference": payment.reference,
            "plan": payment.paystack_plan_code,
            "channels": ["card"],
            "callback_url": callback_url,
            "metadata": {"studigarden_reference": payment.reference, "tier": payment.tier},
        })
        if result.get("reference") != payment.reference or not valid_authorization_url(
            result.get("authorization_url")
        ):
            raise PaystackError("Paystack returned an unexpected test checkout. No redirect was made.")
        payment.authorization_url = result["authorization_url"]
        payment.status = StudyPayment.Status.PENDING
        payment.save(update_fields=["authorization_url", "status", "updated_at"])
        return payment


def _lookup_payment(user, reference):
    if (
        not user or not user.is_authenticated or not user.is_active
        or not isinstance(reference, str)
        or not re.fullmatch(r"SG-[a-f0-9]{32}", reference)
    ):
        raise PaymentNotFound
    payment = StudyPayment.objects.filter(
        user_id=user.pk, reference=reference, mode=StudyPayment.Mode.TEST,
        source=StudyPayment.Source.CHECKOUT,
    ).first()
    if payment is None:
        raise PaymentNotFound
    return payment


def _validate_transaction(result, payment):
    customer = result.get("customer")
    if not isinstance(customer, dict):
        raise PaystackError("Paystack did not return the expected test customer.")
    email = customer.get("email")
    if not (
        result.get("domain") == "test"
        and result.get("reference") == payment.reference
        and isinstance(email, str) and payment.checkout_email
        and email.casefold() == payment.checkout_email.casefold()
    ):
        raise PaystackError("This payment does not match the saved test checkout.")

    status = result.get("status")
    if status not in {"success", "failed", "abandoned", "pending", "processing", "ongoing", "queued"}:
        raise PaystackError("This test transaction is not in a supported payment state.")
    if status != "success":
        return None

    plan_codes = []
    for value in (result.get("plan"), result.get("plan_object")):
        if isinstance(value, str) and value:
            plan_codes.append(value)
        elif isinstance(value, dict) and value.get("plan_code"):
            plan_codes.append(value["plan_code"])
    if not (
        _positive_integer(result.get("id"))
        and type(result.get("amount")) is int
        and result["amount"] == payment.expected_amount_cents
        and result.get("currency") == payment.currency
        and payment.plan == StudyMembership.Plan.MONTHLY
        and payment.tier in {StudyTier.GROW, StudyTier.BLOOM}
        and payment.paystack_plan_code
        and plan_codes and all(code == payment.paystack_plan_code for code in plan_codes)
        and isinstance(customer.get("customer_code"), str)
        and re.fullmatch(r"CUS_[A-Za-z0-9]+", customer["customer_code"])
        and len(customer["customer_code"]) <= 100
    ):
        raise PaystackError("The verified amount, currency or plan does not match this test checkout.")
    try:
        paid_at = parse_datetime(result.get("paid_at", ""))
        if (
            paid_at is None or timezone.is_naive(paid_at)
            or paid_at > timezone.now() + timedelta(minutes=5)
            or paid_at < payment.created_at - timedelta(minutes=5)
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise PaystackError("Paystack did not return a valid payment time.") from None
    return paid_at


def _one_month_after(value):
    year = value.year + (value.month == 12)
    month = 1 if value.month == 12 else value.month + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def verify_test_checkout(*, user, reference):
    client = PaystackTestClient()
    payment = _lookup_payment(user, reference)
    if payment.status == StudyPayment.Status.SUCCEEDED:
        return payment
    if payment.status == StudyPayment.Status.REVERSED:
        raise PaystackError("A reversed payment cannot activate a membership.")

    # Browser query parameters are never evidence of payment. Only this
    # authenticated server-to-server response is considered.
    result = client.verify(payment.reference)
    _validate_transaction(result, payment)
    try:
        with transaction.atomic():
            locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
            payment = StudyPayment.objects.select_for_update().get(pk=payment.pk)
            if not locked_user.is_active:
                raise CheckoutNotAllowed("An active account is required.")
            if payment.status == StudyPayment.Status.SUCCEEDED:
                return payment
            if payment.status == StudyPayment.Status.REVERSED:
                raise PaystackError("A reversed payment cannot activate a membership.")
            paid_at = _validate_transaction(result, payment)
            status = result["status"]
            if status != "success":
                payment.status = {
                    "failed": StudyPayment.Status.FAILED,
                    "abandoned": StudyPayment.Status.ABANDONED,
                }.get(status, StudyPayment.Status.PENDING)
                payment.save(update_fields=["status", "updated_at"])
                return payment

            if StudyPayment.objects.filter(
                mode=StudyPayment.Mode.TEST, paystack_transaction_id=result["id"],
            ).exclude(pk=payment.pk).exists():
                raise PaystackError("That test transaction has already been recorded.")
            membership = StudyMembership.objects.filter(user=locked_user).first()
            if membership and (
                membership.paystack_subscription_code
                or (membership.paid_until and membership.paid_until > timezone.now())
            ):
                raise CheckoutNotAllowed("An existing membership cannot be overwritten by test checkout.")

            # No subscription is created here: supplying the plan at checkout
            # already creates one at Paystack. Webhooks will link renewals later.
            paid_until = _one_month_after(paid_at)
            StudyMembership.objects.update_or_create(user=locked_user, defaults={
                "tier": payment.tier, "plan": StudyMembership.Plan.MONTHLY,
                "payment_mode": StudyMembership.PaymentMode.TEST,
                "status": (StudyMembership.Status.ACTIVE if paid_until > timezone.now()
                           else StudyMembership.Status.EXPIRED),
                "paid_until": paid_until, "grace_until": None,
                "paystack_customer_code": result["customer"]["customer_code"],
                "paystack_subscription_code": None,
            })
            payment.status = StudyPayment.Status.SUCCEEDED
            payment.paystack_transaction_id = result["id"]
            payment.verified_at = timezone.now()
            payment.save(update_fields=["status", "paystack_transaction_id", "verified_at", "updated_at"])
            return payment
    except IntegrityError:
        raise PaystackError("That test payment could not be applied safely. Please check its status again.") from None

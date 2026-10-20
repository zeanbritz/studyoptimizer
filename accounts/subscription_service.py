"""Cancel an owned sandbox subscription only after the provider confirms it."""

import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import StudyMembership, StudyPayment
from .payment_service import CheckoutNotAllowed
from .paystack_client import PaystackError, PaystackTestClient


STOPPED_STATUSES = {"non-renewing", "cancelled", "complete"}
RENEWING_STATUSES = {"active", "attention"}


def _matches_subscription(subscription, customer_code, plan_code):
    if not isinstance(subscription, dict):
        return False
    customer = subscription.get("customer")
    plan = subscription.get("plan")
    return bool(
        subscription.get("domain") == "test"
        # Paystack can omit domain on the embedded customer. The subscription
        # itself must still be test-mode, and its customer code must match our
        # verified payment. Reject any explicit non-test customer mode.
        and isinstance(customer, dict) and customer.get("domain") in (None, "test")
        and customer.get("customer_code") == customer_code
        and isinstance(plan, dict) and plan.get("domain") == "test"
        and plan.get("plan_code") == plan_code
        and isinstance(subscription.get("subscription_code"), str)
        and re.fullmatch(r"SUB_[A-Za-z0-9]+", subscription["subscription_code"])
        and len(subscription["subscription_code"]) <= 100
    )


def _find_subscription(client, membership, payment):
    customer_code = membership.paystack_customer_code
    if not re.fullmatch(r"CUS_[A-Za-z0-9]+", customer_code):
        raise CheckoutNotAllowed("This membership has no verified Paystack test customer.")
    if membership.paystack_subscription_code:
        subscription = client.fetch_subscription(membership.paystack_subscription_code)
        if (
            subscription.get("subscription_code") != membership.paystack_subscription_code
            or not _matches_subscription(subscription, customer_code, payment.paystack_plan_code)
        ):
            raise PaystackError("The Paystack subscription does not match your test membership. Nothing was cancelled.")
        return subscription

    customer = client.fetch_customer(customer_code)
    customer_id = customer.get("id")
    if not (
        customer.get("domain") == "test" and customer.get("customer_code") == customer_code
        and type(customer_id) is int and customer_id > 0
    ):
        raise PaystackError("Paystack did not return the expected test customer. Nothing was cancelled.")
    subscriptions = client.list_customer_subscriptions(customer_id)
    if len(subscriptions) >= 100:
        raise PaystackError("Too many subscriptions to match safely. Review this customer's test subscriptions in Paystack.")
    candidates = []
    for subscription in subscriptions:
        if not _matches_subscription(subscription, customer_code, payment.paystack_plan_code):
            continue
        try:
            created = parse_datetime(subscription.get("createdAt", ""))
        except (TypeError, ValueError):
            continue
        if created is None or timezone.is_naive(created) or created < payment.created_at - timedelta(minutes=5):
            continue
        candidates.append(subscription)
    # Never guess between two matching subscriptions or cancel unrelated plans.
    renewing = [item for item in candidates if item.get("status") in RENEWING_STATUSES]
    matches = renewing or [item for item in candidates if item.get("status") in STOPPED_STATUSES]
    if len(matches) != 1:
        raise PaystackError(
            "Paystack has not returned one matching test subscription yet. "
            "Try cancellation again shortly; if this continues, check your test subscriptions in Paystack."
        )
    return matches[0]


def cancel_test_membership(*, user):
    client = PaystackTestClient()
    if not user or not user.is_authenticated or not user.is_active or not user.pk:
        raise CheckoutNotAllowed("An active account is required.")
    try:
        with transaction.atomic():
            locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
            if not locked_user.is_active:
                raise CheckoutNotAllowed("An active account is required.")
            membership = StudyMembership.objects.select_for_update().filter(
                user=locked_user, payment_mode=StudyMembership.PaymentMode.TEST,
                plan=StudyMembership.Plan.MONTHLY,
            ).first()
            if membership is None:
                raise CheckoutNotAllowed("There is no paid test plan to cancel. Free and beta access do not renew.")
            if membership.status == StudyMembership.Status.NON_RENEWING and membership.paystack_subscription_code:
                return membership
            payment = StudyPayment.objects.filter(
                user=locked_user, tier=membership.tier, mode=StudyPayment.Mode.TEST,
                plan=StudyMembership.Plan.MONTHLY, source=StudyPayment.Source.CHECKOUT,
                status=StudyPayment.Status.SUCCEEDED, verified_at__isnull=False,
            ).exclude(paystack_plan_code="").first()
            if payment is None:
                raise CheckoutNotAllowed("Verify the test payment before cancelling its subscription.")
            subscription = _find_subscription(client, membership, payment)
            code = subscription["subscription_code"]
            if StudyMembership.objects.filter(paystack_subscription_code=code).exclude(pk=membership.pk).exists():
                raise PaystackError("This subscription is already linked to another account. Nothing was cancelled.")
            status = subscription.get("status")
            if status not in STOPPED_STATUSES:
                token = subscription.get("email_token")
                if (
                    status not in RENEWING_STATUSES or not isinstance(token, str)
                    or not 1 <= len(token) <= 500 or any(char in token for char in "\r\n")
                ):
                    raise PaystackError("Paystack has not returned valid test cancellation details. Nothing was cancelled.")
                try:
                    client.disable_subscription(code, token)
                except PaystackError:
                    # A timeout can occur AFTER Paystack accepts cancellation.
                    # Confirm the remote state before reporting success locally.
                    try:
                        checked = client.fetch_subscription(code)
                    except PaystackError:
                        checked = None
                    if not (
                        _matches_subscription(checked, membership.paystack_customer_code, payment.paystack_plan_code)
                        and checked.get("subscription_code") == code
                        and checked.get("status") in STOPPED_STATUSES
                    ):
                        raise PaystackError(
                            "Cancellation could not be confirmed. Check Paystack before assuming future renewals have stopped."
                        ) from None
            membership.paystack_subscription_code = code
            membership.status = StudyMembership.Status.NON_RENEWING
            membership.grace_until = None
            # Preserve paid_until and all study material; never extend or erase it.
            membership.save(update_fields=["paystack_subscription_code", "status", "grace_until", "updated_at"])
            return membership
    except IntegrityError:
        raise PaystackError("The cancellation result could not be saved safely. Check Paystack and try again.") from None

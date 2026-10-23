"""Cancel an owned subscription only after the provider confirms it."""

import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import StudyMembership, StudyPayment, StudyPlanChange
from .payment_service import CheckoutNotAllowed
from .paystack_client import PaystackError, PaystackTestClient, PaystackLiveClient


STOPPED_STATUSES = {"non-renewing", "cancelled", "complete", "completed"}
RENEWING_STATUSES = {"active", "attention"}


def _matches_subscription(subscription, customer_code, plan_code, mode="test"):
    if not isinstance(subscription, dict):
        return False
    customer = subscription.get("customer")
    plan = subscription.get("plan")
    return bool(
        subscription.get("domain") == mode
        # Paystack can omit domain on the embedded customer. The subscription
        # itself must still be test-mode, and its customer code must match our
        # verified payment. Reject any explicit non-test customer mode.
        and isinstance(customer, dict) and customer.get("domain") in (None, mode)
        and customer.get("customer_code") == customer_code
        and isinstance(plan, dict) and plan.get("domain") == mode
        and plan.get("plan_code") == plan_code
        and isinstance(subscription.get("subscription_code"), str)
        and re.fullmatch(r"SUB_[A-Za-z0-9]+", subscription["subscription_code"])
        and len(subscription["subscription_code"]) <= 100
    )


def _find_subscription(client, membership, payment):
    mode = membership.payment_mode
    customer_code = membership.paystack_customer_code
    if not re.fullmatch(r"CUS_[A-Za-z0-9]+", customer_code):
        raise CheckoutNotAllowed("This membership has no verified Paystack customer.")
    if membership.paystack_subscription_code:
        subscription = client.fetch_subscription(membership.paystack_subscription_code)
        if (
            subscription.get("subscription_code") != membership.paystack_subscription_code
            or not _matches_subscription(subscription, customer_code, payment.paystack_plan_code, mode)
        ):
            raise PaystackError("The Paystack subscription does not match your membership. Nothing was cancelled.")
        return subscription

    customer = client.fetch_customer(customer_code)
    customer_id = customer.get("id")
    if not (
        customer.get("domain") == mode and customer.get("customer_code") == customer_code
        and type(customer_id) is int and customer_id > 0
    ):
        raise PaystackError("Paystack did not return the expected customer. Nothing was cancelled.")
    subscriptions = client.list_customer_subscriptions(customer_id)
    if len(subscriptions) >= 100:
        raise PaystackError("Too many subscriptions to match safely. Contact support before continuing.")
    candidates = []
    for subscription in subscriptions:
        if not _matches_subscription(subscription, customer_code, payment.paystack_plan_code, mode):
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
            "Paystack has not returned one matching subscription yet. "
            "Try cancellation again shortly; if this continues, contact support."
        )
    needs_exact_link = mode == "live" and (
        StudyPayment.objects.filter(
            user_id=payment.user_id, mode="live", source="checkout",
            paystack_plan_code=payment.paystack_plan_code, discarded_at__isnull=False,
        ).exists() or StudyPlanChange.objects.filter(payment=payment, kind="restart").exists()
    )
    if needs_exact_link:
        from .discarded_checkouts import invoice_transaction_ids
        canonical = client.fetch_subscription(matches[0]["subscription_code"])
        if (not _matches_subscription(canonical, customer_code, payment.paystack_plan_code, mode)
                or canonical.get("subscription_code") != matches[0]["subscription_code"]
                or payment.paystack_transaction_id not in invoice_transaction_ids(canonical)):
            raise PaystackError("The current subscription could not be distinguished safely from a replaced checkout. Nothing was cancelled.")
        return canonical
    return matches[0]


def cancel_test_membership(*, user):
    return _cancel_membership(user=user, client=PaystackTestClient(), mode="test")


def cancel_live_membership(*, user):
    return _cancel_membership(user=user, client=PaystackLiveClient(), mode="live")


def _cancel_membership(*, user, client, mode, allow_inactive=False):
    if not user or not user.is_authenticated or (not user.is_active and not allow_inactive) or not user.pk:
        raise CheckoutNotAllowed("An active account is required.")
    if mode == "live":
        from .reactivation_service import request_reactivation_cancellation, process_reactivation_change
        reactivation = request_reactivation_cancellation(user=user)
        if reactivation:
            reactivation = process_reactivation_change(reactivation.pk)
            if not reactivation.cancelled_at:
                raise PaystackError("Renewal cancellation is still being confirmed. Check Profile before assuming billing has stopped.")
        from .downgrade_cancellation import request_schedule_cancellation
        from .downgrade_service import process_downgrade_change
        change = request_schedule_cancellation(user=user, restore_current=False, allow_inactive=allow_inactive)
        if change:
            change = process_downgrade_change(change.pk)
            if not change.cancelled_at:
                raise PaystackError("Cancellation is being confirmed. Check your Profile before assuming future billing has stopped.")
    try:
        with transaction.atomic():
            locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
            if not locked_user.is_active and not allow_inactive:
                raise CheckoutNotAllowed("An active account is required.")
            membership = StudyMembership.objects.select_for_update().filter(
                user=locked_user, payment_mode=mode,
                plan=StudyMembership.Plan.MONTHLY,
            ).first()
            if membership is None:
                raise CheckoutNotAllowed("There is no verified paid plan to cancel. Free and beta access do not renew.")
            if membership.status == StudyMembership.Status.NON_RENEWING and membership.paystack_subscription_code:
                return membership
            from .membership_proof import membership_payment
            payment = membership_payment(membership)
            if payment is None:
                raise CheckoutNotAllowed("Verify the payment before cancelling its subscription.")
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
                    raise PaystackError("Paystack has not returned valid cancellation details. Nothing was cancelled.")
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
                        _matches_subscription(checked, membership.paystack_customer_code, payment.paystack_plan_code, mode)
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

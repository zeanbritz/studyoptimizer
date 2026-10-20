"""Read-only, privacy-safe diagnostics for local subscription matching."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.management.commands.create_paystack_test_user import _require_disposable_preview
from accounts.models import StudyMembership, StudyPayment
from accounts.paystack_client import PaystackError, PaystackTestClient
from accounts.subscription_service import _matches_subscription


def _mode(value):
    if not isinstance(value, dict):
        return "not an object"
    domain = value.get("domain")
    return domain if domain in ("test", "live") else "missing or unsupported"


def _time_check(value, payment):
    if value is None or value == "":
        return "missing"
    try:
        created = parse_datetime(value)
    except (TypeError, ValueError):
        return "invalid"
    if created is None:
        return "invalid"
    if timezone.is_naive(created):
        return "no timezone"
    if created < payment.created_at - timedelta(minutes=5):
        return "older than this checkout"
    return "valid for this checkout"


class Command(BaseCommand):
    help = "Read-only cancellation check for one disposable local test account."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        _require_disposable_preview()
        user = get_user_model().objects.using("default").filter(username=options["username"]).first()
        if user is None:
            raise CommandError("That local test account was not found.")
        membership = StudyMembership.objects.using("default").filter(
            user=user, payment_mode=StudyMembership.PaymentMode.TEST,
            plan=StudyMembership.Plan.MONTHLY,
        ).first()
        if membership is None:
            raise CommandError("That account has no monthly test membership to check.")
        payment = StudyPayment.objects.using("default").filter(
            user=user, tier=membership.tier, mode=StudyPayment.Mode.TEST,
            plan=StudyMembership.Plan.MONTHLY, source=StudyPayment.Source.CHECKOUT,
            status=StudyPayment.Status.SUCCEEDED, verified_at__isnull=False,
        ).exclude(paystack_plan_code="").first()
        if payment is None:
            raise CommandError("That account has no matching verified test checkout.")

        self.stdout.write("Read-only check. No accounts, payments or subscriptions will be changed.")
        client = PaystackTestClient()
        try:
            self.stdout.write("Fetching the saved test customer (GET only)...")
            customer = client.fetch_customer(membership.paystack_customer_code)
            self.stdout.write("Customer mode: " + _mode(customer))
            if not (
                customer.get("domain") == "test"
                and customer.get("customer_code") == membership.paystack_customer_code
                and type(customer.get("id")) is int and customer["id"] > 0
            ):
                raise CommandError("Customer details did not match. Stopped before listing subscriptions.")
            self.stdout.write("Listing that customer's subscriptions (GET only)...")
            subscriptions = client.list_customer_subscriptions(customer["id"])
            self.stdout.write(f"Subscriptions returned: {len(subscriptions)}")
            for index, subscription in enumerate(subscriptions[:10], start=1):
                self.stdout.write(f"Subscription {index}:")
                self._report(subscription, membership, payment)
            if len(subscriptions) > 10:
                self.stdout.write("Only the first 10 entries are described.")
            if membership.paystack_subscription_code:
                self.stdout.write("Checking the saved subscription link (GET only)...")
                self._report(client.fetch_subscription(membership.paystack_subscription_code), membership, payment)
        except PaystackError:
            # API exception text may include credentials; never print it.
            raise CommandError("A read-only Paystack lookup failed. No changes were made.") from None
        self.stdout.write("Check complete. No cancellation was attempted.")

    def _report(self, subscription, membership, payment):
        if not isinstance(subscription, dict):
            self.stdout.write("  Entry is not an object.")
            return
        customer = subscription.get("customer")
        plan = subscription.get("plan")
        status = subscription.get("status")
        status = status if status in ("active", "attention", "non-renewing", "cancelled", "complete") else "missing or unsupported"
        self.stdout.write("  Status: " + status)
        self.stdout.write("  Subscription mode: " + _mode(subscription))
        self.stdout.write("  Customer mode: " + _mode(customer))
        self.stdout.write("  Plan mode: " + _mode(plan))
        self.stdout.write("  Customer matches: " + str(
            isinstance(customer, dict) and customer.get("customer_code") == membership.paystack_customer_code
        ))
        self.stdout.write("  Plan matches: " + str(
            isinstance(plan, dict) and plan.get("plan_code") == payment.paystack_plan_code
        ))
        self.stdout.write("  Required ownership fields match: " + str(_matches_subscription(
            subscription, membership.paystack_customer_code, payment.paystack_plan_code,
        )))
        self.stdout.write("  createdAt: " + _time_check(subscription.get("createdAt"), payment))
        self.stdout.write("  created_at: " + _time_check(subscription.get("created_at"), payment))
        self.stdout.write("  Cancellation token present: " + str(
            isinstance(subscription.get("email_token"), str) and bool(subscription["email_token"])
        ))

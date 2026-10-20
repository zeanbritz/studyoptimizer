import io
from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import StudyMembership, StudyPayment
from .paystack_client import PaystackError
from .test_paystack_checkout import SANDBOX


COMMAND_MODULE = "accounts.management.commands.check_paystack_test_subscription"


@override_settings(**SANDBOX)
class SubscriptionDiagnosticTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="local-diagnostic")
        self.membership = StudyMembership.objects.create(
            user=self.user, tier="grow", plan="monthly", payment_mode="test",
            status="active", paid_until=timezone.now() + timedelta(days=30),
            paystack_customer_code="CUS_owner",
        )
        self.payment = StudyPayment.objects.create(
            user=self.user, tier="grow", plan="monthly", mode="test", status="succeeded",
            expected_amount_cents=3500, paystack_plan_code="PLN_owned", verified_at=timezone.now(),
        )
        self.api = Mock()
        self.api.fetch_customer.return_value = {"id": 9, "domain": "test", "customer_code": "CUS_owner"}
        self.subscription = {
            "domain": "test", "subscription_code": "SUB_owned", "status": "active",
            "customer": {"domain": "test", "customer_code": "CUS_owner", "email": "private@example.com"},
            "plan": {"domain": "test", "plan_code": "PLN_owned"},
            "createdAt": timezone.now().isoformat(), "email_token": "privateCancellationToken",
            "authorization": {"authorization_code": "privateCardAuthorization"},
        }
        self.api.list_customer_subscriptions.return_value = [self.subscription]
        self.api.fetch_subscription.return_value = self.subscription

    def run_check(self):
        output = io.StringIO()
        with patch(COMMAND_MODULE + "._require_disposable_preview"), patch(
            COMMAND_MODULE + ".PaystackTestClient", return_value=self.api,
        ):
            call_command("check_paystack_test_subscription", username=self.user.username, stdout=output)
        return output.getvalue()

    def test_get_only_check_preserves_all_local_data_and_never_prints_secrets(self):
        memberships = list(StudyMembership.objects.values())
        payments = list(StudyPayment.objects.values())
        users = list(get_user_model().objects.values())
        output = self.run_check()
        self.assertIn("Subscriptions returned: 1", output)
        self.assertIn("Required ownership fields match: True", output)
        self.assertIn("Cancellation token present: True", output)
        self.assertEqual([call[0] for call in self.api.mock_calls], ["fetch_customer", "list_customer_subscriptions"])
        self.assertEqual(list(StudyMembership.objects.values()), memberships)
        self.assertEqual(list(StudyPayment.objects.values()), payments)
        self.assertEqual(list(get_user_model().objects.values()), users)
        for private in ("private@example.com", "privateCancellationToken", "privateCardAuthorization"):
            self.assertNotIn(private, output)

    def test_empty_list_is_reported(self):
        self.api.list_customer_subscriptions.return_value = []
        self.assertIn("Subscriptions returned: 0", self.run_check())

    def test_omitted_embedded_customer_mode_is_not_reported_as_ownership_failure(self):
        self.subscription["customer"].pop("domain")
        output = self.run_check()
        self.assertIn("Customer mode: missing or unsupported", output)
        self.assertIn("Required ownership fields match: True", output)
        self.api.disable_subscription.assert_not_called()

    def test_timestamp_alias_and_missing_modes_are_distinguished(self):
        self.subscription["created_at"] = self.subscription.pop("createdAt")
        self.subscription["plan"].pop("domain")
        output = self.run_check()
        self.assertIn("createdAt: missing", output)
        self.assertIn("created_at: valid for this checkout", output)
        self.assertIn("Plan mode: missing or unsupported", output)
        self.assertIn("Required ownership fields match: False", output)

    def test_saved_link_only_adds_a_get_lookup(self):
        self.membership.paystack_subscription_code = "SUB_owned"
        self.membership.save(update_fields=["paystack_subscription_code"])
        self.run_check()
        self.assertEqual([call[0] for call in self.api.mock_calls], [
            "fetch_customer", "list_customer_subscriptions", "fetch_subscription",
        ])

    def test_gateway_errors_do_not_reveal_exception_secrets(self):
        self.api.fetch_customer.side_effect = PaystackError("sk_test_private privateCancellationToken")
        with self.assertRaisesMessage(CommandError, "read-only Paystack lookup failed") as raised:
            self.run_check()
        self.assertNotIn("sk_test_private", str(raised.exception))
        self.assertNotIn("privateCancellationToken", str(raised.exception))

    def test_wrong_customer_stops_before_listing(self):
        self.api.fetch_customer.return_value["customer_code"] = "CUS_other"
        with self.assertRaisesMessage(CommandError, "Customer details did not match"):
            self.run_check()
        self.api.list_customer_subscriptions.assert_not_called()

    def test_live_membership_or_unverified_checkout_is_refused_before_network(self):
        for mode, verified_at in (("live", timezone.now()), ("test", None)):
            StudyMembership.objects.filter(pk=self.membership.pk).update(payment_mode=mode)
            StudyPayment.objects.filter(pk=self.payment.pk).update(verified_at=verified_at)
            with self.subTest(mode=mode), self.assertRaises(CommandError):
                self.run_check()
        self.assertEqual(self.api.mock_calls, [])

    def test_environment_guard_runs_before_network_or_account_lookup(self):
        with patch(COMMAND_MODULE + "._require_disposable_preview", side_effect=CommandError("wrong DB")):
            with patch(COMMAND_MODULE + ".PaystackTestClient") as api, self.assertRaises(CommandError):
                call_command("check_paystack_test_subscription", username=self.user.username, stdout=io.StringIO())
        api.assert_not_called()

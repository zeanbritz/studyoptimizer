"""Live integration contract tests. All provider calls use fake data/mocks."""

import hashlib
import hmac
import io
import json
from datetime import timedelta
from unittest.mock import Mock, patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .access import get_study_tier
from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment
from .payment_service import CheckoutNotAllowed
from .payment_webhooks import process_live_payment_receipt, process_test_payment_receipt
from .paystack_checkout import (
    PaymentNotFound, _one_month_after, initialize_live_checkout, verify_live_checkout,
)
from .paystack_client import (
    PaystackError, PaystackLiveClient, live_billing_enabled, live_callback_url, live_checkout_enabled,
)
from .subscription_service import cancel_live_membership
from .subscription_webhooks import process_live_subscription_receipt
from .management.commands.process_paystack_live_events import process_batch


LIVE = {
    "DEBUG": False, "PAYSTACK_LIVE_ENABLED": True, "PAYSTACK_LIVE_CHECKOUT_ENABLED": True,
    "PAYSTACK_LIVE_SECRET_KEY": "sk_live_fakeAutomatedTestOnly",
    "PAYSTACK_TEST_SECRET_KEY": "sk_test_otherFakeKey",
    "PAYSTACK_LIVE_BASE_URL": "https://studigarden.com",
    "PAYSTACK_LIVE_PLAN_CODES": {"grow": "PLN_growLive", "bloom": "PLN_bloomLive"},
    "ALLOWED_HOSTS": ["studigarden.com", "localhost", "testserver"],
    "SECURE_SSL_REDIRECT": False,
}


@override_settings(**LIVE)
class LiveGatesTests(SimpleTestCase):
    def test_enabled_configuration_and_fixed_https_callback(self):
        self.assertTrue(live_billing_enabled())
        self.assertTrue(live_checkout_enabled())
        self.assertEqual(live_callback_url(), "https://studigarden.com/payments/paystack/return/")

    def test_debug_test_key_wrong_host_and_disabled_flags_fail_closed(self):
        for setting, value in (
            ("DEBUG", True), ("PAYSTACK_LIVE_SECRET_KEY", "sk_test_notLive"),
            ("PAYSTACK_LIVE_SECRET_KEY", ""), ("PAYSTACK_LIVE_ENABLED", False),
            ("PAYSTACK_LIVE_BASE_URL", "https://evil.example"),
        ):
            with self.subTest(setting=setting), override_settings(**{setting: value}):
                self.assertFalse(live_billing_enabled())
                self.assertFalse(live_checkout_enabled())
                with self.assertRaises(PaystackError):
                    PaystackLiveClient()

    def test_pausing_sales_does_not_disable_cancellation_or_notifications(self):
        with override_settings(PAYSTACK_LIVE_CHECKOUT_ENABLED=False):
            self.assertTrue(live_billing_enabled())
            self.assertFalse(live_checkout_enabled())
            self.assertEqual(PaystackLiveClient().mode, "live")

    def test_distinct_valid_plan_codes_are_required_for_sales(self):
        for codes in ({}, {"grow": "PLN_same", "bloom": "PLN_same"}, {"grow": "bad", "bloom": "PLN_b"}):
            with override_settings(PAYSTACK_LIVE_PLAN_CODES=codes):
                self.assertFalse(live_checkout_enabled())

    @patch("accounts.paystack_client.build_opener")
    def test_live_client_uses_only_live_key_and_fixed_provider_host(self, opener):
        response = Mock(status=200)
        response.read.return_value = b'{"status":true,"data":{"domain":"live"}}'
        opener.return_value.open.return_value.__enter__.return_value = response
        PaystackLiveClient().verify("SG-reference")
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.paystack.co/transaction/verify/SG-reference")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + LIVE["PAYSTACK_LIVE_SECRET_KEY"])


@override_settings(**LIVE)
class LiveCheckoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="live-contract", email="contract@example.com")
        EmailAddress.objects.create(user=self.user, email=self.user.email, primary=True, verified=True)
        self.plan = {"domain": "live", "plan_code": "PLN_growLive", "amount": 3500, "currency": "ZAR", "interval": "monthly"}
        self.fetch = patch.object(PaystackLiveClient, "fetch_plan", return_value=self.plan).start()
        self.initialize = patch.object(PaystackLiveClient, "initialize", side_effect=lambda payload: {
            "reference": payload["reference"], "authorization_url": "https://checkout.paystack.com/liveContract",
        }).start()
        self.verify = patch.object(PaystackLiveClient, "verify").start()
        self.network = patch("accounts.paystack_client.build_opener", side_effect=AssertionError("Real network forbidden")).start()
        self.addCleanup(patch.stopall)
        self.client = Client(HTTP_HOST="studigarden.com")
        self.client.force_login(self.user)

    def start(self, tier="grow"):
        return initialize_live_checkout(user=self.user, tier=tier)

    def successful(self, payment):
        return {
            "id": 9001, "domain": "live", "status": "success", "reference": payment.reference,
            "amount": payment.expected_amount_cents, "currency": "ZAR", "paid_at": timezone.now().isoformat(),
            "customer": {"customer_code": "CUS_liveOwner", "email": payment.checkout_email},
            "plan": payment.paystack_plan_code, "plan_object": {"domain": "live", "plan_code": payment.paystack_plan_code},
        }

    def confirm(self, payment):
        self.verify.return_value = self.successful(payment)
        return verify_live_checkout(user=self.user, reference=payment.reference)

    def test_server_sets_price_mode_plan_callback_and_card_channel(self):
        payment = self.start()
        payload = self.initialize.call_args.args[0]
        self.assertEqual((payment.mode, payment.expected_amount_cents), ("live", 3500))
        self.assertEqual((payload["plan"], payload["currency"], payload["channels"]), ("PLN_growLive", "ZAR", ["card"]))
        self.assertEqual(payload["callback_url"], live_callback_url())
        self.assertFalse(StudyMembership.objects.exists())
        self.assertEqual(get_study_tier(self.user), "free")

    def test_bloom_server_price_is_9000_cents(self):
        self.plan.update(plan_code="PLN_bloomLive", amount=9000)
        self.assertEqual(self.start("bloom").expected_amount_cents, 9000)

    def test_test_mode_provider_plan_is_rejected_before_checkout(self):
        self.plan["domain"] = "test"
        with self.assertRaises(PaystackError):
            self.start()
        self.initialize.assert_not_called()
        self.assertEqual(StudyPayment.objects.get().status, "created")

    def test_repeated_click_resumes_one_checkout(self):
        first = self.start()
        self.assertEqual(self.start().pk, first.pk)
        self.initialize.assert_called_once()
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_timeout_preserves_reference_and_retry_cannot_create_new_charge(self):
        self.initialize.side_effect = PaystackError("Timeout")
        with self.assertRaises(PaystackError):
            self.start()
        reference = StudyPayment.objects.get().reference
        with self.assertRaises(PaystackError):
            self.start()
        self.assertEqual(StudyPayment.objects.count(), 1)
        self.assertTrue(all(call.args[0]["reference"] == reference for call in self.initialize.call_args_list))

    def test_pending_other_tier_is_blocked(self):
        self.start()
        with self.assertRaises(CheckoutNotAllowed):
            self.start("bloom")
        self.initialize.assert_called_once()

    def test_unsuccessful_checkout_reuses_original_link_not_second_charge(self):
        payment = self.start()
        for state in ("failed", "abandoned"):
            StudyPayment.objects.filter(pk=payment.pk).update(status=state)
            self.assertEqual(self.start().reference, payment.reference)
        self.initialize.assert_called_once()
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_pricing_live_buttons_send_users_to_profile_for_consent(self):
        response = self.client.get(reverse("pricing"), secure=True)
        self.assertContains(response, "Choose Grow")
        self.assertContains(response, "Choose Bloom")
        self.assertNotContains(response, "Grow coming soon")
        self.initialize.assert_not_called()

    def test_beta_and_unverified_accounts_are_not_charged(self):
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        with self.assertRaises(CheckoutNotAllowed):
            self.start()
        self.user.beta_lifetime_access = False
        self.user.save(update_fields=["beta_lifetime_access"])
        EmailAddress.objects.filter(user=self.user).update(verified=False)
        with self.assertRaises(CheckoutNotAllowed):
            self.start()
        self.initialize.assert_not_called()

    def test_verified_payment_grants_live_access_once(self):
        payment = self.confirm(self.start())
        member = StudyMembership.objects.get()
        self.assertEqual((member.payment_mode, member.tier, member.status), ("live", "grow", "active"))
        self.assertEqual(get_study_tier(self.user), "grow")
        verify_live_checkout(user=self.user, reference=payment.reference)
        self.verify.assert_called_once()
        self.assertEqual(StudyMembership.objects.get().paid_until, member.paid_until)
        with self.assertRaises(CheckoutNotAllowed):
            self.start()

    def test_provider_amount_mode_and_nested_modes_are_checked(self):
        payment = self.start()
        for field, value in (("amount", 1), ("domain", "test"), ("currency", "USD"),
                             ("plan_object", {"domain": "test", "plan_code": payment.paystack_plan_code})):
            with self.subTest(field=field):
                self.verify.return_value = {**self.successful(payment), field: value}
                with self.assertRaises(PaystackError):
                    verify_live_checkout(user=self.user, reference=payment.reference)
                self.assertFalse(StudyMembership.objects.exists())

    def test_test_checkout_cannot_be_verified_as_live_or_by_other_owner(self):
        payment = self.start()
        StudyPayment.objects.filter(pk=payment.pk).update(mode="test")
        with self.assertRaises(PaymentNotFound):
            verify_live_checkout(user=self.user, reference=payment.reference)
        self.verify.assert_not_called()

    def test_start_requires_confirmation_csrf_https_and_production_host(self):
        url = reverse("start_live_checkout")
        self.assertEqual(self.client.post(url, {"tier": "grow"}, secure=True).status_code, 302)
        self.initialize.assert_not_called()
        strict = Client(enforce_csrf_checks=True, HTTP_HOST="studigarden.com")
        strict.force_login(self.user)
        self.assertEqual(strict.post(url, {"tier": "grow", "confirm_subscription": "yes"}, secure=True).status_code, 403)
        for secure, host in ((False, "studigarden.com"), (True, "localhost")):
            self.assertEqual(self.client.post(url, {"tier": "grow", "confirm_subscription": "yes"}, secure=secure, HTTP_HOST=host).status_code, 404)
        self.initialize.assert_not_called()

    def test_valid_post_redirects_only_to_trusted_checkout(self):
        response = self.client.post(reverse("start_live_checkout"), {"tier": "grow", "confirm_subscription": "yes"}, secure=True)
        self.assertEqual(response["Location"], "https://checkout.paystack.com/liveContract")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_disabled_sales_still_allow_verification(self):
        payment = self.start()
        with override_settings(PAYSTACK_LIVE_CHECKOUT_ENABLED=False):
            with self.assertRaises(PaystackError):
                self.start()
            self.confirm(payment)
        self.assertEqual(get_study_tier(self.user), "grow")

    def test_profile_shows_live_actions_and_no_test_buttons(self):
        response = self.client.get(reverse("my_plan"), secure=True)
        self.assertContains(response, "Subscribe to Grow")
        self.assertContains(response, "Refund and cancellation policy")
        self.assertNotContains(response, "Local test checkout")
        self.assertNotContains(response, LIVE["PAYSTACK_LIVE_SECRET_KEY"])

    def test_disabled_production_configuration_hides_controls(self):
        with override_settings(PAYSTACK_LIVE_ENABLED=False):
            response = self.client.get(reverse("my_plan"), secure=True)
            self.assertNotContains(response, "Subscribe to Grow")
            self.assertEqual(self.client.post(reverse("start_live_checkout"), secure=True).status_code, 404)

    def test_cancellation_works_with_sales_off_and_preserves_paid_time(self):
        self.confirm(self.start())
        member = StudyMembership.objects.get()
        member.paystack_subscription_code = "SUB_owned"
        member.save(update_fields=["paystack_subscription_code"])
        subscription = {
            "domain": "live", "subscription_code": "SUB_owned", "status": "active",
            "customer": {"customer_code": "CUS_liveOwner"},
            "plan": {"domain": "live", "plan_code": "PLN_growLive"}, "email_token": "privateToken",
        }
        with override_settings(PAYSTACK_LIVE_CHECKOUT_ENABLED=False), \
                patch.object(PaystackLiveClient, "fetch_subscription", return_value=subscription), \
                patch.object(PaystackLiveClient, "disable_subscription", return_value={}) as disable:
            result = cancel_live_membership(user=self.user)
            self.assertEqual(result.status, "non_renewing")
            self.assertEqual(result.paid_until, member.paid_until)
            cancel_live_membership(user=self.user)
            disable.assert_called_once_with("SUB_owned", "privateToken")
        self.assertEqual(get_study_tier(self.user), "grow")

    def test_live_diagnostic_is_read_only(self):
        self.fetch.side_effect = lambda code: {**self.plan, "plan_code": code, "amount": 3500 if "grow" in code else 9000}
        call_command("check_paystack_live", stdout=io.StringIO())
        self.initialize.assert_not_called()
        self.assertFalse(StudyPayment.objects.exists())

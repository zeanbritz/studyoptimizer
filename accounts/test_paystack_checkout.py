"""Mocked sandbox tests: never read a real secret or contact Paystack."""

from datetime import timedelta
from unittest.mock import Mock, patch
from urllib.error import URLError

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .access import get_study_tier
from .models import StudyMembership, StudyPayment, StudyTier
from .payment_service import CheckoutNotAllowed
from .paystack_client import (
    PAYSTACK_USER_AGENT, PaystackError, PaystackTestClient, checkout_callback_url,
    test_checkout_enabled as sandbox_enabled, valid_authorization_url,
)
from .paystack_checkout import (
    PaymentNotFound, _one_month_after, initialize_test_checkout, verify_test_checkout,
)


SANDBOX = {
    "DEBUG": True, "PAYSTACK_TEST_CHECKOUT_ENABLED": True,
    "PAYSTACK_TEST_SECRET_KEY": "sk_test_dummyForAutomatedTests",
    "PAYSTACK_TEST_CALLBACK_BASE_URL": "http://localhost:8000",
    "PAYSTACK_TEST_PLAN_CODES": {"grow": "PLN_growTest", "bloom": "PLN_bloomTest"},
    "ALLOWED_HOSTS": ["localhost", "127.0.0.1", "testserver", "studigarden.com"],
}


@override_settings(**SANDBOX)
class PaystackCheckoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sandbox-student", email="student@example.com", password="test-safe-password",
        )
        EmailAddress.objects.create(user=self.user, email=self.user.email, verified=True, primary=True)
        self.other = get_user_model().objects.create_user(username="other-student")
        self.client = Client(HTTP_HOST="localhost")
        self.plan = {
            "domain": "test", "plan_code": "PLN_growTest", "amount": 3500,
            "currency": "ZAR", "interval": "monthly", "is_deleted": False,
        }
        self.fetch = patch.object(PaystackTestClient, "fetch_plan", return_value=self.plan).start()
        self.initialize = patch.object(PaystackTestClient, "initialize", side_effect=lambda payload: {
            "reference": payload["reference"],
            "authorization_url": "https://checkout.paystack.com/test123",
        }).start()
        self.verify = patch.object(PaystackTestClient, "verify").start()
        self.addCleanup(patch.stopall)

    def start(self, tier=StudyTier.GROW):
        return initialize_test_checkout(user=self.user, tier=tier)

    def success(self, payment, **overrides):
        result = {
            "id": 54321, "domain": "test", "status": "success",
            "reference": payment.reference, "amount": payment.expected_amount_cents,
            "currency": "ZAR", "paid_at": timezone.now().isoformat(),
            "customer": {"email": payment.checkout_email, "customer_code": "CUS_testStudent"},
            "plan": payment.paystack_plan_code,
            "plan_object": {"plan_code": payment.paystack_plan_code},
        }
        result.update(overrides)
        return result

    def confirm(self, payment, **overrides):
        self.verify.return_value = self.success(payment, **overrides)
        return verify_test_checkout(user=self.user, reference=payment.reference)

    def test_initialize_uses_server_snapshot_without_granting_access(self):
        payment = self.start()
        payload = self.initialize.call_args.args[0]
        self.assertEqual(payload["amount"], 3500)
        self.assertEqual(payload["currency"], "ZAR")
        self.assertEqual(payload["plan"], "PLN_growTest")
        self.assertEqual(payload["channels"], ["card"])
        self.assertEqual(payload["callback_url"], "http://localhost:8000/payments/paystack/test/return/")
        self.assertEqual(payment.checkout_email, self.user.email)
        self.assertEqual(payment.status, StudyPayment.Status.PENDING)
        self.assertFalse(StudyMembership.objects.exists())
        self.assertEqual(get_study_tier(self.user), StudyTier.FREE)

    def test_bloom_uses_90_rand_plan(self):
        self.plan.update(plan_code="PLN_bloomTest", amount=9000)
        payment = self.start(StudyTier.BLOOM)
        self.assertEqual(payment.expected_amount_cents, 9000)
        self.assertEqual(self.initialize.call_args.args[0]["plan"], "PLN_bloomTest")

    def test_provider_plan_must_match_before_opening_checkout(self):
        for field, value in (
            ("amount", 9000), ("amount", "3500"), ("currency", "NGN"),
            ("interval", "annually"), ("domain", "live"),
            ("plan_code", "PLN_wrong"), ("is_deleted", True),
        ):
            with self.subTest(field=field):
                self.fetch.return_value = {**self.plan, field: value}
                with self.assertRaises(PaystackError):
                    self.start()
                self.assertFalse(StudyPayment.objects.exists())
        self.initialize.assert_not_called()

    def test_api_failure_rolls_back_attempt_without_membership(self):
        self.initialize.side_effect = PaystackError("Test timeout")
        with self.assertRaises(PaystackError):
            self.start()
        self.assertFalse(StudyPayment.objects.exists())
        self.assertFalse(StudyMembership.objects.exists())

    def test_repeated_click_resumes_original_checkout(self):
        first = self.start()
        self.assertEqual(self.start().pk, first.pk)
        self.assertEqual(StudyPayment.objects.count(), 1)
        self.initialize.assert_called_once()
        self.fetch.assert_called_once()

    def test_pending_checkout_blocks_another_tier(self):
        self.start()
        with self.assertRaises(CheckoutNotAllowed):
            self.start(StudyTier.BLOOM)
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_untrusted_provider_redirect_and_reference_are_rejected(self):
        for url in ("http://checkout.paystack.com/x", "https://checkout.paystack.com.evil.test/x", "https://evil.test/x"):
            self.initialize.side_effect = lambda payload: {"reference": payload["reference"], "authorization_url": url}
            with self.subTest(url=url), self.assertRaises(PaystackError):
                self.start()
            self.assertFalse(StudyPayment.objects.exists())
        self.initialize.side_effect = None
        self.initialize.return_value = {"reference": "wrong", "authorization_url": "https://checkout.paystack.com/x"}
        with self.assertRaises(PaystackError):
            self.start()

    def test_beta_and_unverified_users_cannot_pay(self):
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

    def test_anonymous_and_invalid_tier_are_rejected(self):
        with self.assertRaises(CheckoutNotAllowed):
            initialize_test_checkout(user=AnonymousUser(), tier="grow")
        for tier in ("free", "gold", None, []):
            with self.subTest(tier=tier), self.assertRaises(CheckoutNotAllowed):
                self.start(tier)
        self.fetch.assert_not_called()

    def test_valid_payment_creates_test_only_membership(self):
        payment = self.confirm(self.start())
        membership = StudyMembership.objects.get(user=self.user)
        self.assertEqual(payment.status, StudyPayment.Status.SUCCEEDED)
        self.assertEqual(payment.paystack_transaction_id, 54321)
        self.assertIsNotNone(payment.verified_at)
        self.assertEqual(membership.tier, StudyTier.GROW)
        self.assertEqual(membership.payment_mode, StudyMembership.PaymentMode.TEST)
        self.assertIsNone(membership.paystack_subscription_code)
        self.assertEqual(get_study_tier(self.user), StudyTier.GROW)
        for options in ({"DEBUG": False}, {"PAYSTACK_TEST_CHECKOUT_ENABLED": False}):
            with self.settings(**options):
                self.assertEqual(get_study_tier(self.user), StudyTier.FREE)

    def test_idempotent_callback_never_extends_paid_until(self):
        payment = self.confirm(self.start())
        before = StudyMembership.objects.get(user=self.user).paid_until
        verify_test_checkout(user=self.user, reference=payment.reference)
        self.verify.assert_called_once()
        self.assertEqual(StudyMembership.objects.get(user=self.user).paid_until, before)
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_verified_member_cannot_create_duplicate_subscription(self):
        self.confirm(self.start())
        with self.assertRaises(CheckoutNotAllowed):
            self.start()
        self.initialize.assert_called_once()

    def test_other_user_and_unknown_references_are_not_sent_to_provider(self):
        payment = self.start()
        for user, reference in ((self.other, payment.reference), (self.user, "SG-" + "0" * 32), (self.user, "../anything")):
            with self.subTest(reference=reference), self.assertRaises(PaymentNotFound):
                verify_test_checkout(user=user, reference=reference)
        self.verify.assert_not_called()

    def test_verification_must_match_saved_properties(self):
        payment = self.start()
        for overrides in (
            {"domain": "live"}, {"reference": "wrong"}, {"amount": 1},
            {"amount": "3500"}, {"currency": "USD"}, {"id": True}, {"id": -2},
            {"plan": "PLN_other"}, {"plan_object": {"plan_code": "PLN_other"}},
            {"plan": None, "plan_object": {}},
            {"customer": {"email": "other@example.com", "customer_code": "CUS_wrong"}},
            {"customer": {}}, {"paid_at": None}, {"paid_at": "2020-01-01T00:00:00Z"},
            {"paid_at": "2026-10-20T00:00:00"},
            {"paid_at": (timezone.now() + timedelta(days=1)).isoformat()},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(PaystackError):
                self.confirm(payment, **overrides)
            payment.refresh_from_db()
            self.assertEqual(payment.status, StudyPayment.Status.PENDING)
            self.assertFalse(StudyMembership.objects.exists())

    def test_checkout_email_is_a_snapshot(self):
        payment = self.start()
        self.user.email = "new@example.com"
        self.user.save(update_fields=["email"])
        self.confirm(payment)
        self.assertEqual(get_study_tier(self.user), StudyTier.GROW)

    def test_incomplete_payments_never_unlock_access(self):
        payment = self.start()
        for status in ("failed", "abandoned", "pending", "processing", "queued", "ongoing"):
            self.confirm(payment, status=status)
            self.assertFalse(StudyMembership.objects.exists())
            self.assertEqual(get_study_tier(self.user), StudyTier.FREE)

    def test_verification_timeout_does_not_change_pending_payment(self):
        payment = self.start()
        self.verify.side_effect = PaystackError("Verification unavailable")
        with self.assertRaises(PaystackError):
            verify_test_checkout(user=self.user, reference=payment.reference)
        payment.refresh_from_db()
        self.assertEqual(payment.status, StudyPayment.Status.PENDING)
        self.assertFalse(StudyMembership.objects.exists())

    def test_transaction_id_cannot_be_reused(self):
        payment = self.start()
        StudyPayment.objects.create(
            user=self.other, tier="grow", plan="monthly", mode="test",
            expected_amount_cents=3500, paystack_transaction_id=54321, status="succeeded",
        )
        with self.assertRaises(PaystackError):
            self.confirm(payment)
        self.assertFalse(StudyMembership.objects.exists())

    def test_existing_live_membership_cannot_be_overwritten(self):
        payment = self.start()
        membership = StudyMembership.objects.create(
            user=self.user, tier="bloom", plan="monthly", status="active",
            paid_until=timezone.now() + timedelta(days=30),
        )
        with self.assertRaises(CheckoutNotAllowed):
            self.confirm(payment)
        membership.refresh_from_db()
        self.assertEqual(membership.tier, "bloom")
        self.assertEqual(membership.payment_mode, "live")

    def test_old_payment_does_not_receive_new_month_at_callback_time(self):
        payment = self.start()
        then = timezone.now() - timedelta(days=70)
        StudyPayment.objects.filter(pk=payment.pk).update(created_at=then)
        self.confirm(payment, paid_at=then.isoformat())
        membership = StudyMembership.objects.get(user=self.user)
        self.assertEqual(membership.status, "expired")
        self.assertLess(membership.paid_until, timezone.now())

    def test_public_hostname_disabled_sandbox_and_live_key_are_blocked(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("start_test_checkout"), {"tier": "grow"}, HTTP_HOST="studigarden.com")
        self.assertEqual(response.status_code, 404)
        for options in ({"DEBUG": False}, {"PAYSTACK_TEST_CHECKOUT_ENABLED": False}, {"PAYSTACK_TEST_SECRET_KEY": "sk_live_dummy"}):
            with self.subTest(options=options), self.settings(**options):
                response = self.client.post(reverse("start_test_checkout"), {"tier": "grow"})
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(self.client.get(reverse("pricing")), "Test Grow checkout")
        self.initialize.assert_not_called()

    def test_post_requires_login_csrf_and_server_owned_prices(self):
        response = self.client.post(reverse("start_test_checkout"), {"tier": "grow"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("start_test_checkout")).status_code, 405)
        strict = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        strict.force_login(self.user)
        self.assertEqual(strict.post(reverse("start_test_checkout"), {"tier": "grow"}).status_code, 403)
        response = self.client.post(reverse("start_test_checkout"), {"tier": "grow", "amount": "1", "currency": "USD", "plan": "PLN_fake", "mode": "live"})
        self.assertEqual(response.url, "https://checkout.paystack.com/test123")
        self.assertEqual(self.initialize.call_args.args[0]["amount"], 3500)
        self.assertIn("no-store", response["Cache-Control"])

    def test_fake_success_query_never_unlocks_membership(self):
        payment = self.start()
        self.verify.return_value = self.success(payment, status="pending")
        self.client.force_login(self.user)
        response = self.client.get(reverse("test_checkout_return"), {"reference": payment.reference, "status": "success", "amount": 3500})
        self.assertRedirects(response, reverse("my_plan"))
        self.assertFalse(StudyMembership.objects.exists())

    def test_callback_is_owner_scoped_and_get_only(self):
        payment = self.start()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("test_checkout_return"), {"reference": payment.reference}).status_code, 404)
        self.assertEqual(self.client.post(reverse("test_checkout_return"), {"reference": payment.reference}).status_code, 405)
        self.verify.assert_not_called()

    def test_buttons_and_pending_status_never_render_secret(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("pricing"))
        self.assertContains(response, "Test Grow checkout")
        self.assertContains(response, "Test Bloom checkout")
        self.assertNotContains(response, SANDBOX["PAYSTACK_TEST_SECRET_KEY"])
        self.start()
        response = self.client.get(reverse("my_plan"))
        self.assertContains(response, "Check payment status")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertNotContains(response, SANDBOX["PAYSTACK_TEST_SECRET_KEY"])

    def test_beta_buttons_are_hidden(self):
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("pricing")), "Test Grow checkout")


@override_settings(**SANDBOX)
class PaystackClientTests(SimpleTestCase):
    def test_invalid_keys_and_production_are_refused(self):
        for key in ("", "sk_live_dummy", "pk_test_dummy", "sk_test_bad\r\nheader"):
            with self.settings(PAYSTACK_TEST_SECRET_KEY=key):
                self.assertFalse(sandbox_enabled())
                with self.assertRaises(PaystackError):
                    PaystackTestClient()
        with self.settings(DEBUG=False), self.assertRaises(PaystackError):
            PaystackTestClient()

    def test_callback_must_use_local_address(self):
        for address in ("https://evil.test", "http://localhost@evil.test", "http://localhost:bad", "http://localhost:8000/other", "http://localhost?x=1"):
            with self.settings(PAYSTACK_TEST_CALLBACK_BASE_URL=address), self.assertRaises(PaystackError):
                checkout_callback_url()

    def test_checkout_url_cannot_redirect_elsewhere(self):
        self.assertTrue(valid_authorization_url("https://checkout.paystack.com/sandbox"))
        for value in (None, "javascript:alert(1)", "https://checkout.paystack.com@evil.test/x", "https://checkout.paystack.com:443/x", "https://checkout.paystack.com/x\n"):
            self.assertFalse(valid_authorization_url(value))

    @patch("accounts.paystack_client.build_opener")
    def test_transport_uses_https_bearer_and_timeout(self, opener):
        response = Mock(status=200)
        response.read.return_value = b'{"status":true,"data":{"domain":"test"}}'
        opener.return_value.open.return_value.__enter__.return_value = response
        self.assertEqual(PaystackTestClient().fetch_plan("PLN_test"), {"domain": "test"})
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.paystack.co/plan/PLN_test")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + SANDBOX["PAYSTACK_TEST_SECRET_KEY"])
        self.assertEqual(request.get_header("User-agent"), PAYSTACK_USER_AGENT)
        self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 12)

    @patch("accounts.paystack_client.build_opener")
    def test_errors_never_expose_secret(self, opener):
        opener.return_value.open.side_effect = URLError(SANDBOX["PAYSTACK_TEST_SECRET_KEY"])
        with self.assertRaises(PaystackError) as error:
            PaystackTestClient().verify("SG-test")
        self.assertNotIn(SANDBOX["PAYSTACK_TEST_SECRET_KEY"], str(error.exception))

    @patch("accounts.paystack_client.build_opener")
    def test_invalid_json_and_oversized_response_fail_closed(self, opener):
        response = Mock(status=200)
        opener.return_value.open.return_value.__enter__.return_value = response
        for raw in (b"not json", b"[]", b'{"status":false,"data":{}}', b'{"status":true,"data":[]}', b"x" * 1_048_577):
            response.read.return_value = raw
            with self.subTest(raw=raw[:20]), self.assertRaises(PaystackError):
                PaystackTestClient().fetch_plan("PLN_test")

    def test_month_end_and_year_change(self):
        value = timezone.now().replace(year=2026, month=1, day=31)
        self.assertEqual(_one_month_after(value).day, 28)
        self.assertEqual(_one_month_after(value).month, 2)
        self.assertEqual(_one_month_after(value.replace(month=12)).year, 2027)

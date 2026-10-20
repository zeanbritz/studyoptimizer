"""Sandbox cancellation tests; all Paystack calls are mocked."""

import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .access import get_study_tier
from .models import StudyMembership, StudyPayment, StudyTier
from .payment_service import CheckoutNotAllowed
from .paystack_client import PaystackError, PaystackTestClient
from .subscription_service import cancel_test_membership
from .test_paystack_checkout import SANDBOX


@override_settings(**SANDBOX)
class SubscriptionCancellationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="cancel-student")
        self.other = get_user_model().objects.create_user(username="another-student")
        self.end_date = timezone.now() + timedelta(days=27)
        self.membership = StudyMembership.objects.create(
            user=self.user, tier="grow", plan="monthly", payment_mode="test",
            status="active", paid_until=self.end_date, paystack_customer_code="CUS_owner",
        )
        self.payment = StudyPayment.objects.create(
            user=self.user, tier="grow", plan="monthly", mode="test", status="succeeded",
            expected_amount_cents=3500, paystack_plan_code="PLN_growTest",
            paystack_transaction_id=98765, verified_at=timezone.now(),
        )
        self.subscription = {
            "domain": "test", "subscription_code": "SUB_owned", "status": "active",
            "customer": {"domain": "test", "customer_code": "CUS_owner", "id": 9},
            "plan": {"domain": "test", "plan_code": "PLN_growTest", "id": 20},
            "createdAt": timezone.now().isoformat(), "email_token": "privateFakeCancellationToken",
        }
        self.customer = patch.object(PaystackTestClient, "fetch_customer", return_value={
            "id": 9, "domain": "test", "customer_code": "CUS_owner",
        }).start()
        self.listing = patch.object(PaystackTestClient, "list_customer_subscriptions", return_value=[self.subscription]).start()
        self.fetch = patch.object(PaystackTestClient, "fetch_subscription", return_value=self.subscription).start()
        self.disable = patch.object(PaystackTestClient, "disable_subscription", return_value={}).start()
        self.addCleanup(patch.stopall)
        self.client = Client(HTTP_HOST="localhost")
        self.url = reverse("cancel_test_membership")

    def assert_unchanged(self):
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "active")
        self.assertEqual(self.membership.paid_until, self.end_date)

    def test_cancellation_stops_provider_renewal_and_keeps_paid_access(self):
        from learning.models import Subject
        subject = Subject.objects.create(user=self.user, name="Maths")
        membership = cancel_test_membership(user=self.user)
        self.disable.assert_called_once_with("SUB_owned", "privateFakeCancellationToken")
        self.assertEqual(membership.status, "non_renewing")
        self.assertEqual(membership.paystack_subscription_code, "SUB_owned")
        self.assertEqual(membership.paid_until, self.end_date)
        self.assertEqual(get_study_tier(self.user), StudyTier.GROW)
        self.assertTrue(Subject.objects.filter(pk=subject.pk).exists())
        StudyMembership.objects.filter(pk=membership.pk).update(paid_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(get_study_tier(self.user), StudyTier.FREE)
        self.assertTrue(Subject.objects.filter(pk=subject.pk).exists())

    def test_cancellation_is_idempotent(self):
        cancel_test_membership(user=self.user)
        result = cancel_test_membership(user=self.user)
        self.disable.assert_called_once()
        self.listing.assert_called_once_with(9)
        self.assertEqual(result.paid_until, self.end_date)

    def test_existing_subscription_code_does_not_require_discovery(self):
        self.membership.paystack_subscription_code = "SUB_owned"
        self.membership.save(update_fields=["paystack_subscription_code"])
        cancel_test_membership(user=self.user)
        self.fetch.assert_called_once_with("SUB_owned")
        self.customer.assert_not_called()
        self.listing.assert_not_called()

    def test_confirmation_accepts_embedded_customer_without_redundant_domain(self):
        self.subscription["customer"].pop("domain")
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"confirm_cancel": "yes"}, follow=True)
        self.assertContains(response, "Future renewals are stopped")
        self.assertNotContains(response, "Confirm cancellation")
        self.disable.assert_called_once_with("SUB_owned", "privateFakeCancellationToken")
        self.customer.assert_called_once_with("CUS_owner")
        self.listing.assert_called_once_with(9)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "non_renewing")
        self.assertEqual(self.membership.paystack_subscription_code, "SUB_owned")
        self.assertEqual(self.membership.paid_until, self.end_date)
        self.assertEqual(get_study_tier(self.user), StudyTier.GROW)

    def test_saved_subscription_accepts_embedded_customer_without_domain(self):
        self.subscription["customer"].pop("domain")
        self.membership.paystack_subscription_code = "SUB_owned"
        self.membership.save(update_fields=["paystack_subscription_code"])
        result = cancel_test_membership(user=self.user)
        self.assertEqual(result.status, "non_renewing")
        self.assertEqual(result.paid_until, self.end_date)
        self.fetch.assert_called_once_with("SUB_owned")
        self.disable.assert_called_once_with("SUB_owned", "privateFakeCancellationToken")

    def test_null_embedded_customer_mode_uses_subscription_test_mode(self):
        self.subscription["customer"]["domain"] = None
        result = cancel_test_membership(user=self.user)
        self.assertEqual(result.status, "non_renewing")
        self.assertEqual(result.paid_until, self.end_date)
        self.disable.assert_called_once_with("SUB_owned", "privateFakeCancellationToken")

    def test_explicit_invalid_customer_modes_still_block_cancellation(self):
        for domain in ("live", "unknown", "", False, [], {}):
            self.subscription["customer"]["domain"] = domain
            with self.subTest(domain=domain), self.assertRaises(PaystackError):
                cancel_test_membership(user=self.user)
            self.assert_unchanged()
        self.disable.assert_not_called()

    def test_missing_customer_mode_does_not_allow_wrong_owner_plan_or_subscription_mode(self):
        self.subscription["customer"].pop("domain")
        for path, value in (
            (("domain",), "live"), (("domain",), None),
            (("customer", "customer_code"), "CUS_other"),
            (("customer",), 9), (("customer",), {}),
            (("plan", "domain"), "live"), (("plan", "domain"), None),
            (("plan", "plan_code"), "PLN_other"),
        ):
            changed = deepcopy(self.subscription)
            target = changed
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            self.listing.return_value = [changed]
            with self.subTest(path=path, value=value), self.assertRaises(PaystackError):
                cancel_test_membership(user=self.user)
            self.assert_unchanged()
        self.disable.assert_not_called()

    def test_timeout_reconciliation_accepts_omitted_customer_domain_but_checks_owner(self):
        self.subscription["customer"].pop("domain")
        self.disable.side_effect = PaystackError("Timed out after acceptance")
        stopped = {**deepcopy(self.subscription), "status": "non-renewing"}
        self.fetch.return_value = {
            **stopped, "customer": {"customer_code": "CUS_other"},
        }
        with self.assertRaisesMessage(PaystackError, "could not be confirmed"):
            cancel_test_membership(user=self.user)
        self.assert_unchanged()
        self.fetch.return_value = stopped
        result = cancel_test_membership(user=self.user)
        self.assertEqual(result.status, "non_renewing")
        self.assertEqual(result.paid_until, self.end_date)

    def test_cancellation_uses_original_plan_snapshot_not_current_catalog(self):
        with self.settings(PAYSTACK_TEST_PLAN_CODES={"grow": "PLN_replacement"}):
            result = cancel_test_membership(user=self.user)
        self.assertEqual(result.status, "non_renewing")
        self.disable.assert_called_once_with("SUB_owned", "privateFakeCancellationToken")

    def test_subscription_already_linked_to_another_account_is_not_cancelled(self):
        StudyMembership.objects.create(
            user=self.other, tier="grow", plan="monthly", payment_mode="test",
            paystack_subscription_code="SUB_owned",
        )
        with self.assertRaises(PaystackError):
            cancel_test_membership(user=self.user)
        self.disable.assert_not_called()
        self.assert_unchanged()

    def test_already_stopped_provider_states_do_not_send_disable_again(self):
        for status in ("non-renewing", "cancelled", "complete"):
            with self.subTest(status=status):
                self.membership.status = "active"
                self.membership.paystack_subscription_code = None
                self.membership.save(update_fields=["status", "paystack_subscription_code"])
                self.subscription["status"] = status
                result = cancel_test_membership(user=self.user)
                self.assertEqual(result.status, "non_renewing")
                self.assertEqual(result.paid_until, self.end_date)
        self.disable.assert_not_called()

    def test_timeout_does_not_falsely_report_cancellation(self):
        self.disable.side_effect = PaystackError("Timed out")
        with self.assertRaisesMessage(PaystackError, "could not be confirmed"):
            cancel_test_membership(user=self.user)
        self.assert_unchanged()

    def test_lost_acknowledgement_is_reconciled_from_provider(self):
        self.disable.side_effect = PaystackError("Timed out after acceptance")
        self.fetch.return_value = {**self.subscription, "status": "non-renewing"}
        result = cancel_test_membership(user=self.user)
        self.assertEqual(result.status, "non_renewing")
        self.assertEqual(result.paid_until, self.end_date)

    def test_failed_reconciliation_keeps_local_plan_unchanged(self):
        self.disable.side_effect = PaystackError("Timed out")
        self.fetch.side_effect = PaystackError("Unavailable")
        with self.assertRaisesMessage(PaystackError, "could not be confirmed"):
            cancel_test_membership(user=self.user)
        self.assert_unchanged()

    def test_another_user_cannot_cancel_this_membership(self):
        with self.assertRaises(CheckoutNotAllowed):
            cancel_test_membership(user=self.other)
        self.disable.assert_not_called()
        self.customer.assert_not_called()
        self.assert_unchanged()

    def test_anonymous_and_inactive_accounts_cannot_cancel(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        for user in (None, AnonymousUser(), self.user):
            with self.subTest(user=user), self.assertRaises(CheckoutNotAllowed):
                cancel_test_membership(user=user)
        self.disable.assert_not_called()

    def test_live_or_prepaid_membership_cannot_be_cancelled_by_test_endpoint(self):
        for changes in ({"payment_mode": "live"}, {"payment_mode": "test", "plan": "yearly"}):
            StudyMembership.objects.filter(pk=self.membership.pk).update(**changes)
            with self.subTest(changes=changes), self.assertRaises(CheckoutNotAllowed):
                cancel_test_membership(user=self.user)
        self.disable.assert_not_called()

    def test_payment_must_have_been_verified(self):
        for changes in ({"verified_at": None}, {"verified_at": timezone.now(), "status": "pending"}):
            StudyPayment.objects.filter(pk=self.payment.pk).update(**changes)
            with self.subTest(changes=changes), self.assertRaises(CheckoutNotAllowed):
                cancel_test_membership(user=self.user)
        self.disable.assert_not_called()

    def test_mismatched_customer_plan_or_mode_is_never_cancelled(self):
        self.membership.paystack_subscription_code = "SUB_owned"
        self.membership.save(update_fields=["paystack_subscription_code"])
        for path, value in (
            (("domain",), "live"), (("customer", "customer_code"), "CUS_other"),
            (("customer", "domain"), "live"), (("plan", "domain"), "live"),
            (("plan", "plan_code"), "PLN_other"), (("subscription_code",), "SUB_other"),
        ):
            changed = deepcopy(self.subscription)
            target = changed
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            self.fetch.return_value = changed
            with self.subTest(path=path), self.assertRaises(PaystackError):
                cancel_test_membership(user=self.user)
            self.assert_unchanged()
        self.disable.assert_not_called()

    def test_missing_or_ambiguous_subscriptions_fail_safely(self):
        for items in ([], [self.subscription, {**self.subscription, "subscription_code": "SUB_duplicate"}], [self.subscription] * 100):
            self.listing.return_value = items
            with self.subTest(count=len(items)), self.assertRaises(PaystackError):
                cancel_test_membership(user=self.user)
            self.assert_unchanged()
        self.disable.assert_not_called()

    def test_old_unrelated_subscription_is_not_selected(self):
        self.subscription["createdAt"] = (self.payment.created_at - timedelta(days=10)).isoformat()
        with self.assertRaises(PaystackError):
            cancel_test_membership(user=self.user)
        self.disable.assert_not_called()

    def test_invalid_customer_response_prevents_subscription_lookup(self):
        self.customer.return_value = {"id": 9, "domain": "live", "customer_code": "CUS_owner"}
        with self.assertRaises(PaystackError):
            cancel_test_membership(user=self.user)
        self.listing.assert_not_called()
        self.disable.assert_not_called()

    def test_missing_cancellation_token_or_unknown_state_is_not_success(self):
        for changes in ({"email_token": ""}, {"email_token": None}, {"status": "unknown"}):
            self.listing.return_value = [{**self.subscription, **changes}]
            with self.subTest(changes=changes), self.assertRaises(PaystackError):
                cancel_test_membership(user=self.user)
            self.assert_unchanged()
        self.disable.assert_not_called()

    def test_expired_paid_period_is_not_extended(self):
        end = timezone.now() - timedelta(days=2)
        StudyMembership.objects.filter(pk=self.membership.pk).update(paid_until=end)
        result = cancel_test_membership(user=self.user)
        self.assertEqual(result.paid_until, end)
        self.assertEqual(get_study_tier(self.user), StudyTier.FREE)

    def test_beta_lifetime_access_is_not_removed(self):
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        cancel_test_membership(user=self.user)
        self.user.refresh_from_db()
        self.assertTrue(self.user.beta_lifetime_access)
        self.assertEqual(get_study_tier(self.user), StudyTier.BLOOM)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("my_plan")), "Your permanent free access remains in place")

    def test_post_requires_explicit_confirmation_and_ignores_foreign_ids(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("my_plan"))
        self.disable.assert_not_called()
        response = self.client.post(self.url, {
            "confirm_cancel": "yes", "user_id": self.other.pk,
            "subscription_code": "SUB_foreign", "token": "untrusted",
        })
        self.assertRedirects(response, reverse("my_plan"))
        self.disable.assert_called_once_with("SUB_owned", "privateFakeCancellationToken")

    def test_post_requires_login_and_csrf_and_get_does_not_cancel(self):
        response = self.client.post(self.url, {"confirm_cancel": "yes"})
        self.assertIn("/login/", response.url)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        strict = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        strict.force_login(self.user)
        self.assertEqual(strict.post(self.url, {"confirm_cancel": "yes"}).status_code, 403)
        self.disable.assert_not_called()

    def test_public_host_disabled_mode_and_live_key_are_blocked(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.url, {"confirm_cancel": "yes"}, HTTP_HOST="studigarden.com").status_code, 404)
        for options in ({"DEBUG": False}, {"PAYSTACK_TEST_CHECKOUT_ENABLED": False}, {"PAYSTACK_TEST_SECRET_KEY": "sk_live_dummy"}):
            with self.subTest(options=options), self.settings(**options):
                self.assertEqual(self.client.post(self.url, {"confirm_cancel": "yes"}).status_code, 404)
        self.disable.assert_not_called()

    def test_profile_confirmation_and_cancelled_status_never_render_token(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("my_plan"))
        self.assertContains(response, "Cancel plan")
        self.assertContains(response, "Confirm cancellation")
        self.assertContains(response, "confirm_cancel")
        self.assertNotContains(response, "privateFakeCancellationToken")
        self.client.post(self.url, {"confirm_cancel": "yes"})
        response = self.client.get(reverse("my_plan"))
        self.assertContains(response, "Future renewals are stopped")
        self.assertNotContains(response, "Confirm cancellation")
        self.assertNotContains(response, "privateFakeCancellationToken")

    def test_free_profile_explains_no_subscription_and_cancellation_after_purchase(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("my_plan"))
        self.assertContains(response, "Plan cancellation")
        self.assertContains(response, "There is no verified paid test plan to cancel")
        self.assertNotContains(response, "Confirm cancellation")


@override_settings(**SANDBOX)
class CancellationClientTests(SimpleTestCase):
    @patch("accounts.paystack_client.build_opener")
    def test_disable_accepts_success_without_data_and_uses_server_token(self, opener):
        response = Mock(status=200)
        response.read.return_value = b'{"status":true,"message":"Subscription disabled successfully"}'
        opener.return_value.open.return_value.__enter__.return_value = response
        result = PaystackTestClient().disable_subscription("SUB_owned", "fake-token")
        self.assertEqual(result, {})
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.paystack.co/subscription/disable")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"code": "SUB_owned", "token": "fake-token"})

    @patch("accounts.paystack_client.build_opener")
    def test_disable_rejects_unsuccessful_or_malformed_acknowledgement(self, opener):
        response = Mock(status=200)
        opener.return_value.open.return_value.__enter__.return_value = response
        for raw in (b'{"status":false}', b'{"status":"true"}', b'{"status":true,"data":[]}', b'not-json'):
            response.read.return_value = raw
            with self.subTest(raw=raw), self.assertRaises(PaystackError):
                PaystackTestClient().disable_subscription("SUB_owned", "fake-token")

    @patch("accounts.paystack_client.build_opener")
    def test_listing_is_customer_scoped_and_accepts_list_only(self, opener):
        response = Mock(status=200)
        response.read.return_value = b'{"status":true,"data":[]}'
        opener.return_value.open.return_value.__enter__.return_value = response
        self.assertEqual(PaystackTestClient().list_customer_subscriptions(9), [])
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.paystack.co/subscription?customer=9&perPage=100&page=1")
        self.assertEqual(request.get_method(), "GET")
        response.read.return_value = b'{"status":true,"data":{}}'
        with self.assertRaises(PaystackError):
            PaystackTestClient().list_customer_subscriptions(9)
        for value in (True, "9", None, -1):
            with self.subTest(value=value), self.assertRaises(PaystackError):
                PaystackTestClient().list_customer_subscriptions(value)

"""Customer confirmations with a stateful fake gateway; no real billing calls."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import test_downgrade_scheduling as downgrade_fixtures
from . import test_upgrades as upgrade_fixtures
from .access import get_study_tier
from .downgrade_service import request_live_downgrade
from .models import StudyMembership, StudyPayment, StudyPlanChange, StudyRefund
from .payment_service import CheckoutNotAllowed
from .plan_changes import quote_plan_change, quote_snapshot
from .test_plan_changes import CHANGE_SETTINGS


@override_settings(**CHANGE_SETTINGS)
class PlanControlsTests(TestCase):
    fixture = downgrade_fixtures.DowngradeSchedulingTests

    def setUp(self):
        # Compose fixture helpers, not TestCase inheritance or imported test
        # classes that accidentally discover/run another module's whole suite.
        self.f = self.fixture(methodName="runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.user = self.f.user
        self.member = self.f.member
        self.client.force_login(self.user)

    def get(self, url, **kwargs):
        return self.client.get(url, secure=True, HTTP_HOST="studigarden.com", **kwargs)

    def post(self, url, data):
        return self.client.post(url, data, secure=True, HTTP_HOST="studigarden.com")

    def url(self, tier="grow"):
        return reverse("change_live_plan", args=[tier])

    def consent(self, url=None):
        response = self.get(url or self.url())
        self.assertEqual(response.status_code, 200)
        return {"confirm_plan_change": "yes", "quote_token": response.context["quote_token"]}

    def test_profile_and_pricing_share_paid_and_free_switch_links_without_gateway_calls(self):
        for name in ("my_plan", "pricing"):
            response = self.get(reverse(name))
            self.assertContains(response, self.url("grow"))
            self.assertContains(response, self.url("free"))
        self.f.verify.assert_not_called()
        self.f.fetch_subscription.assert_not_called()
        self.assertFalse(StudyPlanChange.objects.exists())

    def test_get_shows_zero_now_lower_price_date_and_freezing_without_mutations(self):
        response = self.get(self.url())
        self.assertContains(response, "R0 is due now")
        self.assertContains(response, "R35 per month until cancelled")
        self.assertContains(response, "earliest 7")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertEqual(response.context["quote"].effective_at, self.f.end)
        self.assertIn("no-store", response["Cache-Control"])
        self.f.create.assert_not_called()
        self.f.disable.assert_not_called()
        self.f.verify.assert_not_called()
        self.assertFalse(StudyPlanChange.objects.exists())

    def test_downgrade_post_saves_instruction_not_payment_or_access(self):
        response = self.post(self.url(), self.consent())
        self.assertRedirects(response, reverse("my_plan"), fetch_redirect_response=False)
        change = StudyPlanChange.objects.get(user=self.user)
        self.assertEqual((change.state, change.to_tier, change.monthly_amount_cents), ("queued", "grow", 3500))
        self.assertEqual(change.effective_at, self.f.end)
        self.assertEqual(get_study_tier(self.user), "bloom")
        self.assertEqual(StudyPayment.objects.count(), 1)
        self.f.create.assert_not_called()
        self.f.disable.assert_not_called()

    def test_free_confirmation_authorises_no_new_debit(self):
        url = self.url("free")
        response = self.get(url)
        self.assertContains(response, "no recurring charge")
        self.post(url, self.consent(url))
        change = StudyPlanChange.objects.get()
        self.assertEqual((change.to_tier, change.amount_due_now_cents, change.monthly_amount_cents), ("free", 0, 0))
        self.f.create.assert_not_called()

    def test_missing_consent_or_signature_cannot_save_a_request(self):
        token = self.consent()["quote_token"]
        for data in ({}, {"confirm_plan_change": "yes"}, {"quote_token": token},
                     {"confirm_plan_change": "yes", "quote_token": token + "tampered"}):
            with self.subTest(data=data):
                self.assertEqual(self.post(self.url(), data).status_code, 302)
        self.assertFalse(StudyPlanChange.objects.exists())
        self.f.verify.assert_not_called()

    def test_expired_confirmation_is_rejected(self):
        data = self.consent()
        with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 901):
            self.post(self.url(), data)
        self.assertFalse(StudyPlanChange.objects.exists())

    def test_token_cannot_be_used_for_another_user_or_target_tier(self):
        data = self.consent()
        self.post(self.url("free"), data)
        other = get_user_model().objects.create_user(username="other-plan-student")
        StudyMembership.objects.create(user=other, payment_mode="live", tier="bloom", plan="monthly", status="active", paid_until=self.f.end, paystack_customer_code="CUS_other")
        self.client.force_login(other)
        self.post(self.url("free"), data)
        self.assertFalse(StudyPlanChange.objects.exists())
        self.f.verify.assert_not_called()

    def test_stale_paid_through_status_email_or_configuration_requires_review(self):
        for field, value in (("paid_until", self.f.end + timedelta(days=1)), ("status", "non_renewing"),
                             ("paystack_subscription_code", "SUB_other")):
            data = self.consent()
            original = getattr(self.member, field)
            StudyMembership.objects.filter(pk=self.member.pk).update(**{field: value})
            self.post(self.url(), data)
            StudyMembership.objects.filter(pk=self.member.pk).update(**{field: original})
        data = self.consent()
        with override_settings(PAYSTACK_LIVE_PLAN_CODES={"grow": "PLN_changed", "bloom": "PLN_bloomLive"}):
            self.post(self.url(), data)
        self.assertFalse(StudyPlanChange.objects.exists())
        self.f.verify.assert_not_called()

    def test_service_rechecks_signed_snapshot_under_user_lock(self):
        quote = quote_plan_change(user=self.user, tier="grow")
        saved = quote_snapshot(self.user, quote)
        StudyMembership.objects.filter(pk=self.member.pk).update(status="non_renewing")
        with self.assertRaises(CheckoutNotAllowed):
            request_live_downgrade(user=self.user, tier="grow", expected_quote=saved)
        self.f.verify.assert_not_called()

    def test_form_prices_dates_customer_and_user_identifiers_are_ignored(self):
        data = {**self.consent(), "amount": "1", "effective_at": "2099-01-01", "user_id": "999", "customer_code": "CUS_wrong"}
        self.post(self.url(), data)
        change = StudyPlanChange.objects.get()
        self.assertEqual((change.user_id, change.customer_code, change.effective_at, change.monthly_amount_cents),
                         (self.user.pk, "CUS_owner", self.f.end, 3500))

    def test_duplicate_submission_does_not_open_two_changes(self):
        data = self.consent()
        self.post(self.url(), data)
        self.post(self.url(), data)
        self.assertEqual(StudyPlanChange.objects.count(), 1)
        self.f.create.assert_not_called()

    def test_feature_flag_host_https_and_authentication_fail_closed(self):
        with override_settings(PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False):
            self.assertEqual(self.get(self.url()).status_code, 404)
            self.assertEqual(self.post(self.url(), {}).status_code, 404)
            self.assertNotContains(self.get(reverse("my_plan")), self.url())
        self.assertEqual(self.client.get(self.url(), HTTP_HOST="studigarden.com").status_code, 404)
        self.assertEqual(self.client.get(self.url(), secure=True, HTTP_HOST="localhost").status_code, 404)
        self.client.logout()
        self.assertEqual(self.get(self.url()).status_code, 302)
        self.assertFalse(StudyPlanChange.objects.exists())

    def test_paid_pause_still_allows_free_and_existing_cancellation(self):
        with override_settings(PAYSTACK_LIVE_CHECKOUT_ENABLED=False):
            self.assertEqual(self.get(self.url()).status_code, 302)
            self.assertEqual(self.get(self.url("free")).status_code, 200)

    def test_csrf_protection_and_methods(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url(), self.consent(), secure=True, HTTP_HOST="studigarden.com").status_code, 403)
        self.assertEqual(self.client.put(self.url(), secure=True, HTTP_HOST="studigarden.com").status_code, 405)
        self.assertFalse(StudyPlanChange.objects.exists())

    def test_beta_and_test_memberships_do_not_get_live_switch_controls(self):
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        self.assertNotContains(self.get(reverse("my_plan")), self.url())
        self.assertEqual(self.get(self.url()).status_code, 302)
        self.user.beta_lifetime_access = False
        self.user.save(update_fields=["beta_lifetime_access"])
        StudyMembership.objects.filter(pk=self.member.pk).update(payment_mode="test")
        self.assertEqual(self.get(self.url()).status_code, 302)
        self.f.verify.assert_not_called()

    def test_expired_plan_only_shows_confirmation_without_initializing_checkout(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(paid_until=timezone.now() - timedelta(days=1), status="expired")
        self.assertEqual(self.get(self.url()).status_code, 200)
        self.assertFalse(StudyPlanChange.objects.exists())
        self.f.initialize.assert_not_called()

    def test_pending_status_cancellation_and_restore_are_not_falsely_reported_done(self):
        change = self.f.request()
        response = self.get(reverse("my_plan"))
        self.assertContains(response, "awaiting Paystack confirmation")
        cancel_url = reverse("cancel_scheduled_plan", args=[change.pk])
        self.assertContains(response, cancel_url)
        self.assertContains(response, cancel_url + "?action=keep")
        self.post(cancel_url, {**self.consent(cancel_url), "action": "stop"})
        response = self.get(reverse("my_plan"))
        self.assertContains(response, "Billing changes are not yet confirmed")
        change.refresh_from_db()
        self.assertTrue(change.cancel_requested)
        self.assertIsNone(change.cancelled_at)
        self.f.disable.assert_not_called()

    def test_stop_scheduled_is_available_when_sales_and_switching_paused(self):
        change = self.f.process(self.f.request())
        url = reverse("cancel_scheduled_plan", args=[change.pk])
        with override_settings(PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False, PAYSTACK_LIVE_CHECKOUT_ENABLED=False):
            self.assertEqual(self.get(url + "?action=keep").status_code, 302)
            self.post(url, {**self.consent(url), "action": "stop"})
        change.refresh_from_db()
        self.assertTrue(change.cancel_requested)
        self.assertFalse(change.restore_current)

    def test_keep_choice_requires_its_own_signed_consent_and_preserves_paid_time(self):
        change = self.f.process(self.f.request())
        url = reverse("cancel_scheduled_plan", args=[change.pk])
        stop_data = self.consent(url)
        self.post(url, {**stop_data, "action": "keep"})
        change.refresh_from_db()
        self.assertFalse(change.cancel_requested)
        response = self.get(url + "?action=keep")
        self.assertContains(response, "R90 per month")
        self.post(url, {"confirm_plan_change": "yes", "quote_token": response.context["quote_token"], "action": "keep"})
        change.refresh_from_db()
        self.assertTrue(change.restore_current)
        self.member.refresh_from_db()
        self.assertEqual(self.member.paid_until, self.f.end)

    def test_foreign_schedule_and_stale_membership_are_not_cancellable_through_form(self):
        change = self.f.request()
        url = reverse("cancel_scheduled_plan", args=[change.pk])
        data = {**self.consent(url), "action": "stop"}
        StudyMembership.objects.filter(pk=self.member.pk).update(paid_until=self.f.end + timedelta(days=1))
        self.post(url, data)
        change.refresh_from_db()
        self.assertFalse(change.cancel_requested)
        other = get_user_model().objects.create_user(username="wrong-schedule-owner")
        self.client.force_login(other)
        self.assertEqual(self.get(url).status_code, 404)
        self.assertEqual(self.post(url, data).status_code, 404)

    def test_pending_scheduled_card_does_not_claim_all_future_renewals_stopped(self):
        self.f.process(self.f.request())
        response = self.get(reverse("my_plan"))
        self.assertContains(response, "Grow is scheduled at R35/month")
        self.assertNotContains(response, "Future renewals are stopped. Already-paid access continues")
        self.assertContains(response, "A renewal change is in progress")

    def test_unrelated_and_private_billing_details_are_not_rendered(self):
        change = self.f.request()
        StudyPlanChange.objects.filter(pk=change.pk).update(last_result="AUTH_private_DoNotDisplay")
        response = self.get(reverse("my_plan"))
        for text in ("AUTH_private_DoNotDisplay", "fake-cancel-token", "CUS_owner", "SUB_old"):
            self.assertNotContains(response, text)

    def test_keep_old_plan_requires_canonical_price_and_future_date_before_enable(self):
        change = self.f.process(self.f.request())
        from .downgrade_cancellation import request_schedule_cancellation
        self.f.subscriptions["SUB_old"].update(amount=9000, next_payment_date=self.f.end.isoformat())
        enable = self.f.mock_client("enable_subscription", side_effect=lambda code, token:
                                    self.f.subscriptions[code].update(status="active"))
        request_schedule_cancellation(user=self.user, change_id=change.pk, restore_current=True)
        self.f.subscriptions["SUB_old"]["amount"] = 9100
        result = self.f.process(change)
        self.assertEqual((result.state, result.last_result), ("attention", "resume_price_unconfirmed"))
        enable.assert_not_called()
        self.assertIsNone(result.cancelled_at)

    def test_keep_old_plan_rechecks_next_debit_after_enable_before_reporting_success(self):
        change = self.f.process(self.f.request())
        from .downgrade_cancellation import request_schedule_cancellation
        self.f.subscriptions["SUB_old"].update(amount=9000, next_payment_date=self.f.end.isoformat())
        self.f.mock_client("enable_subscription", side_effect=lambda code, token:
                          self.f.subscriptions[code].update(status="active", next_payment_date=timezone.now().isoformat()))
        request_schedule_cancellation(user=self.user, change_id=change.pk, restore_current=True)
        result = self.f.process(change)
        self.assertEqual((result.state, result.last_result), ("attention", "resume_next_debit_unconfirmed"))
        self.assertIsNone(result.cancelled_at)

    def test_pending_refund_prevents_restoring_old_billing(self):
        change = self.f.process(self.f.request())
        from .downgrade_cancellation import request_schedule_cancellation
        StudyRefund.objects.create(user=self.user, payment=self.f.payment, amount_cents=9000)
        with self.assertRaises(CheckoutNotAllowed):
            request_schedule_cancellation(user=self.user, change_id=change.pk, restore_current=True)
        self.assertNotContains(self.get(reverse("my_plan")), "?action=keep")


@override_settings(**CHANGE_SETTINGS)
class UpgradeControlTests(TestCase):
    def setUp(self):
        self.f = upgrade_fixtures.UpgradeSettlementTests(methodName="runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.client.force_login(self.f.user)
        self.url = reverse("change_live_plan", args=["bloom"])

    def get(self, url=None):
        return self.client.get(url or self.url, secure=True, HTTP_HOST="studigarden.com")

    def post(self, data):
        return self.client.post(self.url, data, secure=True, HTTP_HOST="studigarden.com")

    def test_upgrade_displays_full_new_price_current_period_credit_and_explicit_consent(self):
        response = self.get()
        self.assertContains(response, "R90 is due now")
        self.assertContains(response, "full refund of the Grow payment funding your current billing period")
        self.assertContains(response, "confirm_plan_change")
        self.f.verify.assert_not_called()
        self.f.initialize.assert_not_called()

    def test_upgrade_post_continues_same_safe_checkout_and_does_not_change_access_until_verified(self):
        response = self.get()
        data = {"confirm_plan_change": "yes", "quote_token": response.context["quote_token"]}
        result = self.post(data)
        self.assertEqual(result.url, "https://checkout.paystack.com/fake-upgrade")
        self.assertEqual(result["Referrer-Policy"], "no-referrer")
        self.assertEqual(get_study_tier(self.f.user), "grow")
        self.post(data)
        self.assertEqual(StudyPlanChange.objects.count(), 1)
        self.assertEqual(self.f.initialize.call_count, 1)

    def test_upgrade_service_rechecks_snapshot_before_financial_call(self):
        from .upgrade_service import prepare_live_upgrade
        snapshot = quote_snapshot(self.f.user, quote_plan_change(user=self.f.user, tier="bloom"))
        StudyMembership.objects.filter(pk=self.f.member.pk).update(status="non_renewing")
        with self.assertRaises(CheckoutNotAllowed):
            prepare_live_upgrade(user=self.f.user, expected_quote=snapshot)
        self.f.verify.assert_not_called()
        self.f.initialize.assert_not_called()

    def test_verified_upgrade_shows_separate_refund_status_and_never_claims_bank_credit(self):
        self.f.pay()
        self.f.settle()
        response = self.get(reverse("my_plan"))
        self.assertContains(response, "Bloom plan")
        self.assertContains(response, "Grow upgrade credit")
        self.assertNotContains(response, "Paystack confirmed the full refund")
        refund = StudyRefund.objects.get(reason="upgrade")
        StudyRefund.objects.filter(pk=refund.pk).update(status="completed")
        self.assertContains(self.get(reverse("my_plan")), "Your bank may take additional time")

    def test_attention_status_does_not_disclose_internal_provider_error(self):
        self.f.start()
        StudyPlanChange.objects.update(state="attention", last_result="AUTH_notPublic")
        response = self.get(reverse("my_plan"))
        self.assertContains(response, "could not safely confirm")
        self.assertNotContains(response, "AUTH_notPublic")
        self.assertNotContains(response, self.url)

"""Automatic guarantee tests. All financial provider calls are mocked."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .access import get_study_tier
from .models import StudyMembership, StudyPayment, StudyRefund
from .paystack_checkout import _one_month_after
from .paystack_client import PaystackError, PaystackLiveClient
from .refund_service import (
    RefundNotAllowed, process_live_refund, process_refund_batch,
    request_first_payment_refund,
)
from .test_live_payments import LIVE


REFUND_SETTINGS = {**LIVE, "PAYSTACK_LIVE_REFUNDS_ENABLED": True}


@override_settings(**REFUND_SETTINGS)
class RefundTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="refund-owner", email="owner@example.com")
        self.paid_at = timezone.now() - timedelta(days=1)
        self.payment = StudyPayment.objects.create(
            user=self.user, tier="grow", plan="monthly", mode="live", source="checkout", status="succeeded",
            expected_amount_cents=3500, currency="ZAR", paystack_transaction_id=1001,
            paystack_plan_code="PLN_growLive", checkout_email=self.user.email, verified_at=self.paid_at,
        )
        # A hosted checkout may have been opened days before it was actually paid.
        StudyPayment.objects.filter(pk=self.payment.pk).update(created_at=self.paid_at - timedelta(days=10))
        self.payment.refresh_from_db()
        self.member = StudyMembership.objects.create(
            user=self.user, tier="grow", plan="monthly", payment_mode="live", status="active",
            paid_until=_one_month_after(self.paid_at), paystack_customer_code="CUS_owner",
            paystack_subscription_code="SUB_owner",
        )
        self.charge = {
            "domain": "live", "status": "success", "id": 1001, "reference": self.payment.reference,
            "amount": 3500, "currency": "ZAR", "paid_at": self.paid_at.isoformat(),
            "customer": {"customer_code": "CUS_owner", "email": self.user.email}, "plan": "PLN_growLive",
        }
        self.subscription = {
            "domain": "live", "subscription_code": "SUB_owner", "status": "active",
            "customer": {"customer_code": "CUS_owner"},
            "plan": {"domain": "live", "plan_code": "PLN_growLive"}, "email_token": "privateCancelToken",
        }
        self.provider_refund = {
            "domain": "live", "id": 333, "transaction": 1001,
            "amount": 3500, "currency": "ZAR", "status": "pending",
        }
        self.verify = patch.object(PaystackLiveClient, "verify", return_value=self.charge).start()
        self.fetch_subscription = patch.object(PaystackLiveClient, "fetch_subscription", return_value=self.subscription).start()
        self.disable = patch.object(PaystackLiveClient, "disable_subscription", return_value={}).start()
        self.list_refunds = patch.object(PaystackLiveClient, "list_refunds", return_value=[]).start()
        self.create = patch.object(PaystackLiveClient, "create_full_refund", return_value=self.provider_refund).start()
        self.fetch_refund = patch.object(PaystackLiveClient, "fetch_refund", return_value=self.provider_refund).start()
        self.network = patch("accounts.paystack_client.build_opener", side_effect=AssertionError("Real network forbidden")).start()
        self.addCleanup(patch.stopall)
        self.client = Client(HTTP_HOST="studigarden.com")
        self.client.force_login(self.user)

    def request(self):
        return request_first_payment_refund(self.user)

    def process(self, refund):
        StudyRefund.objects.filter(pk=refund.pk).update(next_attempt_at=None)
        return process_live_refund(refund.pk)

    def complete(self, refund):
        self.provider_refund["status"] = "processed"
        return self.process(refund)

    def assert_no_financial_post(self):
        self.disable.assert_not_called()
        self.create.assert_not_called()

    def test_request_only_creates_durable_owned_record_and_no_provider_calls(self):
        refund = self.request()
        self.assertEqual((refund.user_id, refund.payment_id, refund.amount_cents), (self.user.pk, self.payment.pk, 3500))
        self.assertEqual(refund.status, "requested")
        self.verify.assert_not_called()
        self.assert_no_financial_post()
        self.network.assert_not_called()

    def test_repeated_request_returns_same_record(self):
        refund = self.request()
        self.assertEqual(self.request().pk, refund.pk)
        self.assertEqual(StudyRefund.objects.count(), 1)

    def test_normal_flow_auto_approves_cancels_then_refunds_without_ending_access_early(self):
        refund = self.request()
        result = self.process(refund)
        self.assertEqual(result.status, "processing")
        self.assertIsNotNone(result.approved_at)
        self.assertEqual(result.paid_at, self.paid_at)
        self.assertEqual(result.cancelled_subscription_code, "SUB_owner")
        self.assertEqual(result.paystack_refund_id, 333)
        self.disable.assert_called_once_with("SUB_owner", "privateCancelToken")
        self.create.assert_called_once_with(1001, 3500, f"StudiGarden guarantee request {refund.pk}")
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, "non_renewing")
        self.assertEqual(get_study_tier(self.user), "grow")
        self.assertEqual(self.member.paid_until, _one_month_after(self.paid_at))

    def test_completed_refund_returns_to_free_without_deleting_material(self):
        from learning.models import Subject
        subject = Subject.objects.create(user=self.user, name="Maths")
        refund = self.request()
        self.process(refund)
        result = self.complete(refund)
        self.assertEqual(result.status, "completed")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "reversed")
        self.assertEqual(get_study_tier(self.user), "free")
        self.assertTrue(Subject.objects.filter(pk=subject.pk).exists())
        self.process(refund)
        self.create.assert_called_once()
        self.fetch_refund.assert_called_once_with(333)

    def test_bloom_gets_exact_90_rand_refund(self):
        self.payment.tier = "bloom"
        self.payment.expected_amount_cents = 9000
        self.payment.paystack_plan_code = "PLN_bloomLive"
        self.payment.save()
        StudyMembership.objects.filter(pk=self.member.pk).update(tier="bloom")
        self.subscription["plan"]["plan_code"] = "PLN_bloomLive"
        self.charge.update(amount=9000, plan="PLN_bloomLive")
        self.provider_refund["amount"] = 9000
        refund = self.request()
        self.process(refund)
        self.assertEqual(self.create.call_args.args[1], 9000)

    def test_deadline_uses_paid_time_not_old_checkout_creation_or_later_verification(self):
        refund = self.request()
        self.assertEqual(self.process(refund).status, "processing")
        self.create.assert_called_once()

    def test_request_exactly_at_seven_day_boundary_is_accepted(self):
        refund = self.request()
        self.charge["paid_at"] = (refund.requested_at - timedelta(days=7)).isoformat()
        self.assertEqual(self.process(refund).status, "processing")

    def test_outside_seven_days_is_not_automatically_refunded(self):
        refund = self.request()
        self.charge["paid_at"] = (refund.requested_at - timedelta(days=7, microseconds=1)).isoformat()
        result = self.process(refund)
        self.assertEqual((result.status, result.last_result), ("ineligible", "outside_seven_day_guarantee"))
        self.assert_no_financial_post()
        self.assertEqual(get_study_tier(self.user), "grow")

    def test_on_time_request_stays_eligible_if_processed_after_deadline(self):
        refund = self.request()
        self.charge["paid_at"] = (refund.requested_at - timedelta(days=6)).isoformat()
        later = refund.requested_at + timedelta(days=5)
        with patch("django.utils.timezone.now", return_value=later):
            self.assertEqual(self.process(refund).status, "processing")

    def test_provider_payment_amount_mode_currency_id_and_ownership_must_match(self):
        for field, value in (("amount", 1), ("domain", "test"), ("currency", "USD"), ("id", 1002),
                             ("customer", {"customer_code": "CUS_other", "email": "other@example.com"})):
            refund = self.request()
            original = deepcopy(self.charge)
            self.charge[field] = value
            with self.subTest(field=field):
                self.assertNotEqual(self.process(refund).status, "processing")
                self.assert_no_financial_post()
            self.charge.clear()
            self.charge.update(original)
            StudyRefund.objects.filter(pk=refund.pk).delete()

    def test_verified_first_purchase_is_selected_not_a_renewal(self):
        renewal = StudyPayment.objects.create(
            user=self.user, tier="grow", plan="monthly", mode="live", source="renewal", status="succeeded",
            expected_amount_cents=3500, paystack_transaction_id=1002, verified_at=timezone.now(),
        )
        self.assertEqual(self.request().payment_id, self.payment.pk)
        self.assertNotEqual(self.request().payment_id, renewal.pk)

    def test_cancel_failure_retries_without_submitting_refund(self):
        self.fetch_subscription.side_effect = PaystackError("Unavailable")
        refund = self.request()
        self.assertEqual(self.process(refund).status, "approved")
        self.create.assert_not_called()
        self.fetch_subscription.side_effect = None
        self.assertEqual(self.process(refund).status, "processing")
        self.create.assert_called_once()

    def test_submission_intent_is_saved_before_provider_post(self):
        refund = self.request()
        def submit(*args):
            saved = StudyRefund.objects.get(pk=refund.pk)
            self.assertEqual(saved.status, "submitting")
            self.assertIsNotNone(saved.submitted_at)
            return self.provider_refund
        self.create.side_effect = submit
        self.process(refund)

    def test_ambiguous_timeout_is_reconciled_with_gets_never_second_refund_post(self):
        self.create.side_effect = PaystackError("Timeout after provider accepted request")
        refund = self.request()
        self.assertEqual(self.process(refund).status, "submitting")
        self.assertEqual(self.process(refund).status, "submitting")
        self.create.assert_called_once()
        self.list_refunds.return_value = [self.provider_refund]
        self.provider_refund["status"] = "processed"
        self.assertEqual(self.process(refund).status, "completed")
        self.create.assert_called_once()

    def test_crash_after_committing_intent_does_not_repeat_post(self):
        refund = self.request()
        StudyRefund.objects.filter(pk=refund.pk).update(
            status="submitting", submitted_at=timezone.now(), cancelled_subscription_code="SUB_owner",
        )
        self.assertEqual(self.process(refund).status, "submitting")
        self.create.assert_not_called()

    def test_unconfirmed_submission_requires_attention_after_24_hours(self):
        refund = self.request()
        StudyRefund.objects.filter(pk=refund.pk).update(status="submitting", submitted_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(self.process(refund).status, "attention")
        self.create.assert_not_called()

    def test_existing_full_provider_refund_is_reused_not_repeated(self):
        self.list_refunds.return_value = [self.provider_refund]
        self.provider_refund["status"] = "processed"
        self.assertEqual(self.process(self.request()).status, "completed")
        self.create.assert_not_called()

    def test_existing_partial_or_other_transaction_refunds_are_not_guessed(self):
        refund = self.request()
        self.list_refunds.return_value = [{**self.provider_refund, "amount": 100}]
        self.assertEqual(self.process(refund).status, "attention")
        self.create.assert_not_called()

    def test_wrong_refund_mode_or_transaction_cannot_end_paid_access(self):
        refund = self.request()
        self.provider_refund.update(domain="test", status="processed")
        self.assertNotEqual(self.process(refund).status, "completed")
        self.assertEqual(get_study_tier(self.user), "grow")
        self.assertEqual(self.process(refund).status, "submitting")
        self.create.assert_called_once()

    def test_failed_or_needs_attention_provider_status_does_not_claim_completion(self):
        for provider_status in ("failed", "needs-attention"):
            with self.subTest(status=provider_status):
                refund = self.request()
                self.provider_refund["status"] = provider_status
                self.assertEqual(self.process(refund).status, "attention")
                self.assertEqual(get_study_tier(self.user), "grow")
                StudyRefund.objects.filter(pk=refund.pk).delete()

    def test_deactivated_after_request_can_still_get_money_back(self):
        refund = self.request()
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self.process(refund).status, "processing")
        self.create.assert_called_once()

    def test_beta_privileges_survive_refund(self):
        refund = self.request()
        get_user_model().objects.filter(pk=self.user.pk).update(beta_lifetime_access=True)
        self.process(refund)
        self.complete(refund)
        self.user.refresh_from_db()
        self.assertTrue(self.user.beta_lifetime_access)
        self.assertEqual(get_study_tier(self.user), "bloom")

    def test_different_newer_paid_entitlement_is_not_erased(self):
        refund = self.request()
        self.process(refund)
        StudyPayment.objects.create(user=self.user, tier="bloom", plan="monthly", mode="live", status="succeeded",
            expected_amount_cents=9000, paystack_transaction_id=2222, verified_at=timezone.now())
        StudyMembership.objects.filter(pk=self.member.pk).update(tier="bloom", status="active", paystack_subscription_code="SUB_newer")
        self.complete(refund)
        self.assertEqual(get_study_tier(self.user), "bloom")

    def test_disabled_new_requests_does_not_stop_accepted_refund_processing(self):
        refund = self.request()
        with override_settings(PAYSTACK_LIVE_REFUNDS_ENABLED=False):
            with self.assertRaises(RefundNotAllowed):
                self.request()
            self.assertEqual(self.process(refund).status, "processing")

    def test_no_purchase_or_test_only_purchase_cannot_use_guarantee(self):
        StudyPayment.objects.filter(pk=self.payment.pk).update(mode="test")
        with self.assertRaises(RefundNotAllowed):
            self.request()
        self.assertFalse(StudyRefund.objects.exists())
        self.assert_no_financial_post()

    def test_batch_skips_future_or_terminal_requests(self):
        refund = self.request()
        StudyRefund.objects.filter(pk=refund.pk).update(next_attempt_at=timezone.now() + timedelta(minutes=5))
        self.assertEqual(process_refund_batch(), [])
        StudyRefund.objects.filter(pk=refund.pk).update(status="ineligible", next_attempt_at=None)
        self.assertEqual(process_refund_batch(), [])
        self.assert_no_financial_post()

    def test_post_requires_confirmation_and_does_not_trust_client_amount_or_payment_id(self):
        url = reverse("request_live_refund")
        self.client.post(url, {}, secure=True)
        self.assertFalse(StudyRefund.objects.exists())
        response = self.client.post(url, {"confirm_refund": "yes", "amount": "900000", "payment_id": "99999"}, secure=True)
        self.assertEqual(response.status_code, 302)
        refund = StudyRefund.objects.get()
        self.assertEqual((refund.amount_cents, refund.payment_id), (3500, self.payment.pk))
        self.assert_no_financial_post()

    def test_other_account_cannot_request_someone_elses_refund(self):
        other = get_user_model().objects.create_user(username="other-refund")
        self.client.force_login(other)
        response = self.client.post(reverse("request_live_refund"), {"confirm_refund": "yes", "payment_id": self.payment.pk}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(StudyRefund.objects.exists())

    def test_refund_form_enforces_csrf_post_mode_and_production_host(self):
        url = reverse("request_live_refund")
        self.assertEqual(self.client.get(url, secure=True).status_code, 405)
        strict = Client(enforce_csrf_checks=True, HTTP_HOST="studigarden.com")
        strict.force_login(self.user)
        self.assertEqual(strict.post(url, {"confirm_refund": "yes"}, secure=True).status_code, 403)
        self.assertEqual(self.client.post(url, {"confirm_refund": "yes"}, secure=True, HTTP_HOST="localhost").status_code, 404)
        with override_settings(PAYSTACK_LIVE_REFUNDS_ENABLED=False):
            self.assertEqual(self.client.post(url, {"confirm_refund": "yes"}, secure=True).status_code, 404)
        self.assert_no_financial_post()

    def test_profile_displays_request_and_pending_status_without_provider_calls(self):
        response = self.client.get(reverse("my_plan"), secure=True)
        self.assertContains(response, "Check eligibility and request refund")
        self.request()
        response = self.client.get(reverse("my_plan"), secure=True)
        self.assertContains(response, "Checking eligibility")
        self.assertNotContains(response, "Check eligibility and request refund")
        self.verify.assert_not_called()

    def test_one_refund_per_account_is_enforced_in_database(self):
        self.request()
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudyRefund.objects.create(user=self.user, payment=self.payment, amount_cents=3500)


@override_settings(**REFUND_SETTINGS)
class RefundClientTests(SimpleTestCase):
    @patch.object(PaystackLiveClient, "_request", return_value={})
    def test_refund_post_uses_original_transaction_fixed_currency_and_full_amount(self, request):
        PaystackLiveClient().create_full_refund(1001, 3500, "guarantee-1")
        method, path, payload = request.call_args.args
        self.assertEqual((method, path), ("POST", "/refund"))
        self.assertEqual((payload["transaction"], payload["amount"], payload["currency"]), (1001, 3500, "ZAR"))

    @patch.object(PaystackLiveClient, "_request", return_value=[])
    def test_ambiguous_submission_lookup_is_filtered_to_original_transaction(self, request):
        PaystackLiveClient().list_refunds(1001)
        self.assertEqual(request.call_args.args, ("GET", "/refund?transaction=1001&perPage=100&page=1"))


@override_settings(STUDIGARDEN_SUPPORT_EMAIL="")
class RefundPolicyPageTests(TestCase):
    def test_policy_explains_automatic_first_payment_guarantee_and_preserves_other_rights(self):
        response = self.client.get(reverse("billing_policy"))
        self.assertContains(response, "Automatic 7-day first-payment refund")
        self.assertContains(response, "No reason is required")
        self.assertContains(response, "once per account")
        self.assertContains(response, "A qualifying request needs no manual approval")
        self.assertContains(response, "does not limit, applicable South African consumer rights")
        self.assertContains(response, "Support contact details and the final legal review must be completed")
        self.assertNotContains(response, "support@studigarden.com")

    def test_unconfigured_contact_does_not_advertise_nonexistent_mailbox(self):
        response = self.client.get(reverse("contact"))
        self.assertContains(response, "A working support email address will be published")
        self.assertNotContains(response, "mailto:")

    @override_settings(STUDIGARDEN_SUPPORT_EMAIL="support@example.com")
    def test_only_configured_address_appears_on_contact_and_billing_pages(self):
        for route in ("contact", "billing_policy"):
            response = self.client.get(reverse(route))
            self.assertContains(response, 'mailto:support@example.com')

    @override_settings(STUDIGARDEN_SUPPORT_EMAIL="zd.britz@icloud.com")
    def test_approved_temporary_icloud_contact_works_without_branded_mailbox(self):
        for route in ("contact", "billing_policy"):
            response = self.client.get(reverse(route))
            self.assertContains(response, 'mailto:zd.britz@icloud.com')
            self.assertNotContains(response, "Support contact setup is in progress")
            self.assertNotContains(response, "A working support address will be published")
            self.assertNotContains(response, "support@studigarden.com")

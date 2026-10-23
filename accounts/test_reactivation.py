"""Resume/restart integration against fake Paystack state; real network forbidden."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import test_upgrades as fixtures
from .access import get_study_tier
from .membership_proof import membership_payment
from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment, StudyPlanChange, StudyRefund
from .payment_service import CheckoutNotAllowed
from .payment_webhooks import process_live_payment_receipt
from .paystack_checkout import _one_month_after, verify_live_checkout
from .paystack_client import PaystackError
from .plan_changes import quote_plan_change, quote_snapshot
from .reactivation_service import (
    prepare_live_restart, process_reactivation_change, request_live_resume,
)
from .refund_service import process_live_refund
from .subscription_service import cancel_live_membership
from .subscription_webhooks import process_live_subscription_receipt
from .test_plan_changes import CHANGE_SETTINGS


@override_settings(**CHANGE_SETTINGS)
class ReactivationTests(TestCase):
    def setUp(self):
        self.f = fixtures.UpgradeSettlementTests(methodName="runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.user, self.member = self.f.user, self.f.member
        self.end = self.member.paid_until
        StudyMembership.objects.filter(pk=self.member.pk).update(status="non_renewing")
        old = self.f.subscriptions["SUB_old"]
        old.update(status="non-renewing", amount=3500, next_payment_date=self.end.isoformat(), plan=self.f.plan("PLN_growLive"))
        self.enable = self.f.mock_client("enable_subscription", side_effect=lambda code, token:
                                         self.f.subscriptions[code].update(status="active"))
        self.client.force_login(self.user)

    def expire(self, *, refunded=False):
        paid = timezone.now() - timedelta(days=1 if refunded else 45)
        end = timezone.now() - timedelta(seconds=1) if refunded else _one_month_after(paid)
        StudyPayment.objects.filter(pk=self.f.old.pk).update(
            status="reversed" if refunded else "succeeded", created_at=paid-timedelta(minutes=1), verified_at=paid,
            period_start=None, period_end=None,
        )
        self.f.old.refresh_from_db()
        self.f.charges[self.f.old.reference] = self.f.charge(self.f.old, paid, 101)
        self.f.subscriptions["SUB_old"].update(createdAt=paid.isoformat(), next_payment_date=end.isoformat())
        StudyMembership.objects.filter(pk=self.member.pk).update(status="expired", paid_until=end, grace_until=None)
        self.member.refresh_from_db()
        if refunded:
            StudyRefund.objects.create(user=self.user, payment=self.f.old, amount_cents=3500, status="completed")
        return end

    def resume(self):
        return request_live_resume(user=self.user, tier="grow")

    def process(self, change=None):
        change = change or StudyPlanChange.objects.get(user=self.user)
        StudyPlanChange.objects.filter(pk=change.pk).update(next_attempt_at=None)
        return process_reactivation_change(change.pk)

    def restart(self, tier="bloom"):
        return prepare_live_restart(user=self.user, tier=tier)

    def pay(self, payment, *, tx=202):
        now = timezone.now()
        self.f.charges[payment.reference] = self.f.charge(payment, now, tx)
        self.f.subscriptions["SUB_new"] = self.f.subscription("SUB_new", payment.paystack_plan_code, now)
        self.f.subscriptions["SUB_new"]["invoices"] = [{"transaction": tx}]
        return verify_live_checkout(user=self.user, reference=payment.reference)

    def get(self, url):
        return self.client.get(url, secure=True, HTTP_HOST="studigarden.com")

    def post_confirmation(self, tier):
        url = reverse("change_live_plan", args=[tier])
        page = self.get(url)
        self.assertEqual(page.status_code, 200)
        return self.client.post(url, {"confirm_plan_change": "yes", "quote_token": page.context["quote_token"]}, secure=True, HTTP_HOST="studigarden.com")

    def test_resume_records_zero_now_without_enabling_or_adding_paid_time(self):
        change = self.resume()
        self.assertEqual((change.kind, change.state, change.amount_due_now_cents, change.monthly_amount_cents), ("resume", "queued", 0, 3500))
        self.member.refresh_from_db()
        self.assertEqual((self.member.status, self.member.paid_until), ("non_renewing", self.end))
        self.enable.assert_not_called()
        self.f.initialize.assert_not_called()
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_worker_resumes_exact_existing_subscription_and_preserves_paid_time(self):
        result = self.process(self.resume())
        self.assertEqual((result.state, result.last_result), ("applied", "renewals_resumed"))
        self.enable.assert_called_once_with("SUB_old", "fake-cancel-token")
        self.member.refresh_from_db()
        self.assertEqual((self.member.status, self.member.paid_until), ("active", self.end))
        self.f.initialize.assert_not_called()
        self.assertFalse(StudyRefund.objects.exists())

    def test_resume_duplicate_clicks_and_worker_replays_do_not_duplicate_enable(self):
        one, two = self.resume(), self.resume()
        self.assertEqual(one.pk, two.pk)
        self.process(one)
        self.process(one)
        self.enable.assert_called_once()
        self.assertEqual(StudyPlanChange.objects.count(), 1)

    def test_resume_timeout_after_provider_acceptance_is_get_confirmed(self):
        def accepted(code, token):
            self.f.subscriptions[code]["status"] = "active"
            raise PaystackError("fake timeout")
        self.enable.side_effect = accepted
        self.assertEqual(self.process(self.resume()).state, "applied")
        self.enable.assert_called_once()

    def test_uncertain_enable_keeps_durable_intent_and_get_reconciles_without_repeat(self):
        fetch = self.f.fetch_subscription.side_effect
        unavailable = [False]
        def accepted(code, token):
            self.f.subscriptions[code]["status"] = "active"
            unavailable[0] = True
            raise PaystackError("fake timeout")
        def canonical(code):
            if unavailable[0]:
                raise PaystackError("fake GET timeout")
            return fetch(code)
        self.enable.side_effect, self.f.fetch_subscription.side_effect = accepted, canonical
        result = self.process(self.resume())
        self.assertEqual(result.state, "submitting")
        self.assertIsNotNone(result.subscription_posted_at)
        unavailable[0] = False
        self.assertEqual(self.process(result).state, "applied")
        self.enable.assert_called_once()

    def test_wrong_next_date_or_price_cannot_enable_resume(self):
        change = self.resume()
        self.f.subscriptions["SUB_old"]["amount"] = 9000
        result = self.process(change)
        self.assertEqual((result.state, result.last_result), ("queued", "resume_terms_cleanup_required"))
        self.assertTrue(result.cancel_requested)
        self.assertEqual(self.process(result).state, "cancelled")
        self.enable.assert_not_called()

    def test_expired_before_worker_is_stopped_instead_of_enabled(self):
        change = self.resume()
        with patch("accounts.reactivation_service.timezone.now", return_value=self.end+timedelta(seconds=1)):
            result = self.process(change)
        self.assertEqual((result.state, result.last_result), ("cancelled", "resume_period_ended"))
        self.enable.assert_not_called()
        self.member.refresh_from_db()
        self.assertEqual(self.member.paid_until, self.end)

    def test_normal_cancel_retires_queued_resume_before_it_can_enable(self):
        self.resume()
        result = cancel_live_membership(user=self.user)
        self.assertEqual(result.status, "non_renewing")
        self.assertEqual(StudyPlanChange.objects.get().state, "cancelled")
        self.enable.assert_not_called()

    def test_pending_refund_cannot_resume_and_approved_refund_can_cancel_it(self):
        change = self.resume()
        StudyRefund.objects.create(user=self.user, payment=self.f.old, amount_cents=3500)
        result = self.process(change)
        self.assertEqual(result.last_result, "refund_confirmation_pending")
        self.enable.assert_not_called()
        cancel_live_membership(user=self.user)
        self.assertEqual(StudyPlanChange.objects.get().state, "cancelled")

    def test_inactive_or_beta_after_consent_stops_instead_of_enabling(self):
        change = self.resume()
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self.process(change).state, "cancelled")
        self.enable.assert_not_called()

    def test_new_switching_pause_does_not_abandon_accepted_resume(self):
        self.resume()
        with override_settings(PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False, PAYSTACK_LIVE_CHECKOUT_ENABLED=False):
            self.assertEqual(self.process().state, "applied")
        self.enable.assert_called_once()

    def test_resume_request_refuses_wrong_scope_or_refunded_funding(self):
        self.f.subscriptions["SUB_old"]["customer"]["customer_code"] = "CUS_foreign"
        with self.assertRaises(PaystackError):
            self.resume()
        self.assertFalse(StudyPlanChange.objects.exists())
        self.enable.assert_not_called()

    def test_restart_must_expire_and_stop_old_billing_before_checkout(self):
        self.expire()
        self.f.subscriptions["SUB_old"]["status"] = "active"
        def initialize(payload):
            self.assertEqual(self.f.subscriptions["SUB_old"]["status"], "non-renewing")
            return {"reference": payload["reference"], "authorization_url": "https://checkout.paystack.com/fake-restart"}
        self.f.initialize.side_effect = initialize
        payment = self.restart()
        change = StudyPlanChange.objects.get()
        self.assertEqual((change.kind, change.state, payment.tier, payment.expected_amount_cents), ("restart", "checkout", "bloom", 9000))
        self.assertIsNotNone(change.old_stopped_at)
        self.assertEqual(get_study_tier(self.user), "free")
        self.enable.assert_not_called()

    def test_restart_unconfirmed_stop_does_not_initialize(self):
        self.expire()
        self.f.subscriptions["SUB_old"]["status"] = "active"
        self.f.disable.side_effect = PaystackError("fake cancellation timeout")
        with self.assertRaises(PaystackError):
            self.restart()
        self.f.initialize.assert_not_called()
        self.assertEqual(StudyPlanChange.objects.count(), 1)
        self.assertEqual(get_study_tier(self.user), "free")

    def test_restart_timeout_keeps_reference_and_repeated_clicks_never_create_two_payments(self):
        self.expire()
        self.f.initialize.side_effect = PaystackError("fake timeout")
        with self.assertRaises(PaystackError):
            self.restart()
        ref = StudyPlanChange.objects.get().payment.reference
        self.assertIsNotNone(StudyPlanChange.objects.get().old_stopped_at)
        self.f.initialize.side_effect = lambda data: {"reference": data["reference"], "authorization_url": "https://checkout.paystack.com/fake-restart"}
        payment = self.restart()
        self.assertEqual(payment.reference, ref)
        self.assertEqual(self.restart().pk, payment.pk)
        self.assertEqual(StudyPayment.objects.count(), 2)
        self.assertEqual(StudyPlanChange.objects.count(), 1)

    def test_only_verified_restart_payment_activates_fresh_month_no_old_period_credit(self):
        self.expire()
        payment = self.restart()
        before = timezone.now()
        verified = self.pay(payment)
        self.member.refresh_from_db()
        self.assertEqual(get_study_tier(self.user), "bloom")
        self.assertGreaterEqual(self.member.paid_until, _one_month_after(before))
        self.assertEqual(self.member.paid_until, verified.period_end)
        self.assertEqual(StudyPlanChange.objects.get().state, "applied")
        self.assertFalse(StudyRefund.objects.exists())
        self.pay(payment)
        self.member.refresh_from_db()
        self.assertEqual(self.member.paid_until, verified.period_end)

    def test_refunded_history_only_proves_ownership_and_does_not_reset_guarantee(self):
        self.expire(refunded=True)
        self.assertIsNone(membership_payment(self.member))
        payment = self.restart("grow")
        self.assertEqual(get_study_tier(self.user), "free")
        self.pay(payment)
        self.assertEqual(get_study_tier(self.user), "grow")
        self.assertEqual(StudyRefund.objects.filter(reason="first_payment").count(), 1)
        self.assertEqual(StudyPayment.objects.get(pk=self.f.old.pk).status, "reversed")

    def test_reversed_without_completed_refund_cannot_prove_restart_history(self):
        self.expire()
        StudyPayment.objects.filter(pk=self.f.old.pk).update(status="reversed")
        with self.assertRaises(CheckoutNotAllowed):
            self.restart()
        self.f.initialize.assert_not_called()

    def test_restart_rejects_current_funded_time_or_unreconciled_recent_debit(self):
        with self.assertRaises(CheckoutNotAllowed):
            self.restart()
        self.expire()
        self.f.subscriptions["SUB_old"]["most_recent_invoice"] = {
            "paid": True, "status": "success", "period_end": (timezone.now()+timedelta(days=25)).isoformat(), "transaction": 999,
        }
        with self.assertRaises(CheckoutNotAllowed):
            self.restart()
        self.f.initialize.assert_not_called()

    def test_restart_refuses_unfinished_other_checkout_or_pending_financial_work(self):
        self.expire()
        StudyPayment.objects.create(user=self.user, mode="live", tier="bloom", plan="monthly", expected_amount_cents=9000)
        with self.assertRaises(CheckoutNotAllowed):
            self.restart()
        self.f.initialize.assert_not_called()

    def test_wrong_amount_or_mode_cannot_activate_restart(self):
        self.expire()
        payment = self.restart()
        self.f.charges[payment.reference] = self.f.charge(payment, timezone.now(), 202)
        self.f.charges[payment.reference]["amount"] = 3500
        with self.assertRaises(PaystackError):
            verify_live_checkout(user=self.user, reference=payment.reference)
        self.assertEqual(get_study_tier(self.user), "free")

    def test_cancel_pending_restart_discards_checkout_and_late_paid_link_goes_to_refund(self):
        self.expire()
        payment = self.restart()
        old_end = self.member.paid_until
        cancel_live_membership(user=self.user)
        payment.refresh_from_db()
        self.assertIsNotNone(payment.discarded_at)
        self.pay(payment)
        self.assertEqual(get_study_tier(self.user), "free")
        self.member.refresh_from_db()
        self.assertEqual(self.member.paid_until, old_end)
        refund = StudyRefund.objects.get(reason="discarded_checkout")
        self.assertEqual(process_live_refund(refund.pk).status, "processing")
        self.assertEqual(self.f.subscriptions["SUB_new"]["status"], "non-renewing")

    def test_restart_paid_after_account_deactivation_is_recovered_by_signed_notification(self):
        self.expire()
        payment = self.restart()
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.f.charges[payment.reference] = self.f.charge(payment, timezone.now(), 202)
        receipt = PaystackWebhookReceipt.objects.create(mode="live", event_type="charge.success", payload_sha256="inactive-restart", snapshot={
            "schema_version": 1, "domain": "live", "transaction_reference": payment.reference, "transaction_id": 202,
        })
        self.assertEqual(process_live_payment_receipt(receipt.pk).processing_status, "processed")
        payment.refresh_from_db()
        self.assertIsNotNone(payment.discarded_at)
        self.assertTrue(StudyRefund.objects.filter(payment=payment).exists())

    def test_restart_cannot_overwrite_a_new_paid_month_that_won_the_race(self):
        self.expire()
        payment = self.restart()
        StudyMembership.objects.filter(pk=self.member.pk).update(status="active", paid_until=timezone.now()+timedelta(days=25))
        self.pay(payment)
        self.assertTrue(StudyRefund.objects.filter(payment=payment, reason="discarded_checkout").exists())
        self.assertEqual(get_study_tier(self.user), "grow")

    def test_new_restart_requires_exact_subscription_charge_link_not_old_same_tier_metadata(self):
        self.expire(refunded=True)
        payment = self.restart("grow")
        self.pay(payment)
        def receipt(code, key):
            return PaystackWebhookReceipt.objects.create(mode="live", event_type="subscription.create", payload_sha256=key, snapshot={
                "schema_version": 1, "domain": "live", "subscription_code": code,
            })
        old = process_live_subscription_receipt(receipt("SUB_old", "old-restart-metadata").pk)
        self.assertEqual(old.processing_status, "ignored")
        new = process_live_subscription_receipt(receipt("SUB_new", "new-restart-metadata").pk)
        self.assertEqual(new.processing_status, "processed")
        self.member.refresh_from_db()
        self.assertEqual(self.member.paystack_subscription_code, "SUB_new")

    def test_profile_and_confirmation_display_resume_price_date_and_no_charge(self):
        profile = self.get(reverse("my_plan"))
        self.assertContains(profile, "Resume Grow renewals")
        response = self.get(reverse("change_live_plan", args=["grow"]))
        self.assertContains(response, "R0 is due now")
        self.assertContains(response, "does not add another paid month")
        self.assertEqual(self.post_confirmation("grow").status_code, 302)
        self.enable.assert_not_called()

    def test_profile_and_confirmation_display_restart_and_allow_same_checkout_continuation(self):
        self.expire()
        self.assertContains(self.get(reverse("my_plan")), "Restart Bloom")
        response = self.post_confirmation("bloom")
        self.assertTrue(response.url.startswith("https://checkout.paystack.com/"))
        profile = self.get(reverse("my_plan"))
        self.assertContains(profile, "Continue Bloom checkout")
        self.assertContains(profile, "Check restart payment status")
        self.assertContains(profile, reverse("cancel_live_plan"))

    def test_refunded_restart_still_has_cancel_control_without_current_entitlement_proof(self):
        self.expire(refunded=True)
        self.restart("grow")
        self.assertContains(self.get(reverse("my_plan")), reverse("cancel_live_plan"))

    def test_signed_snapshot_rechecked_for_resume_and_restart(self):
        snapshot = quote_snapshot(self.user, quote_plan_change(user=self.user, tier="grow"))
        StudyMembership.objects.filter(pk=self.member.pk).update(paid_until=self.end+timedelta(days=1))
        with self.assertRaises(CheckoutNotAllowed):
            request_live_resume(user=self.user, tier="grow", expected_quote=snapshot)
        self.expire()
        snapshot = quote_snapshot(self.user, quote_plan_change(user=self.user, tier="bloom"))
        StudyMembership.objects.filter(pk=self.member.pk).update(paystack_customer_code="CUS_changed")
        with self.assertRaises(CheckoutNotAllowed):
            prepare_live_restart(user=self.user, tier="bloom", expected_quote=snapshot)
        self.f.initialize.assert_not_called()

    def test_restart_free_beta_test_and_disabled_modes_remain_guarded(self):
        self.expire()
        with override_settings(PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False):
            with self.assertRaises(CheckoutNotAllowed):
                self.restart()
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        with self.assertRaises(CheckoutNotAllowed):
            self.restart()
        self.f.initialize.assert_not_called()

    def test_live_worker_runs_accepted_resume_even_when_new_sales_are_paused(self):
        self.resume()
        with override_settings(PAYSTACK_LIVE_CHECKOUT_ENABLED=False, PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False):
            call_command("process_paystack_live_events", once=True, verbosity=0)
        self.assertEqual(StudyPlanChange.objects.get().state, "applied")

    def test_verified_new_renewal_after_resume_adds_only_its_absolute_period(self):
        self.process(self.resume())
        end = _one_month_after(self.end)
        sub = self.f.subscriptions["SUB_old"]
        sub["most_recent_invoice"] = {
            "id": 433, "domain": "live", "invoice_code": "INV_resume333", "subscription": 12,
            "customer": 9, "amount": 3500, "currency": "ZAR", "paid": True, "status": "success",
            "transaction": 333, "period_start": self.end.isoformat(), "period_end": end.isoformat(),
        }
        self.f.charges["resume-renewal-333"] = {
            **self.f.charge(self.f.old, self.end, 333), "reference": "resume-renewal-333",
        }
        receipt = PaystackWebhookReceipt.objects.create(mode="live", event_type="invoice.update", payload_sha256="resume-renewal", snapshot={
            "schema_version": 1, "domain": "live", "invoice_code": "INV_resume333", "subscription_code": "SUB_old",
            "transaction_reference": "resume-renewal-333", "transaction_id": 333,
        })
        with patch("accounts.reactivation_service.timezone.now", return_value=self.end+timedelta(seconds=5)):
            result = process_live_payment_receipt(receipt.pk)
            self.assertEqual(result.processing_status, "processed")
        self.member.refresh_from_db()
        self.assertEqual(self.member.paid_until, end)

    def test_pending_resume_holds_invoice_until_enable_confirmation_without_extending_access(self):
        self.resume()
        sub = self.f.subscriptions["SUB_old"]
        sub["status"] = "active"
        end = _one_month_after(self.end)
        sub["most_recent_invoice"] = {
            "id": 433, "domain": "live", "invoice_code": "INV_resume333", "subscription": 12,
            "customer": 9, "amount": 3500, "currency": "ZAR", "paid": True, "status": "success",
            "transaction": 333, "period_start": self.end.isoformat(), "period_end": end.isoformat(),
        }
        self.f.charges["resume-renewal-333"] = {**self.f.charge(self.f.old, self.end, 333), "reference": "resume-renewal-333"}
        receipt = PaystackWebhookReceipt.objects.create(mode="live", event_type="invoice.update", payload_sha256="pending-resume-invoice", snapshot={
            "schema_version": 1, "domain": "live", "invoice_code": "INV_resume333", "subscription_code": "SUB_old",
            "transaction_reference": "resume-renewal-333", "transaction_id": 333,
        })
        with patch("accounts.reactivation_service.timezone.now", return_value=self.end+timedelta(seconds=5)):
            result = process_live_payment_receipt(receipt.pk)
        self.assertEqual((result.processing_status, result.last_result), ("retry", "resume_confirmation_pending"))
        self.member.refresh_from_db()
        self.assertEqual(self.member.paid_until, self.end)

    def test_old_restart_renewal_is_refunded_without_touching_chosen_new_subscription(self):
        self.expire()
        payment = self.restart()
        self.pay(payment)
        self.member.refresh_from_db()
        selected_end = self.member.paid_until
        StudyMembership.objects.filter(pk=self.member.pk).update(paystack_subscription_code="SUB_new")
        start = timezone.now()
        sub = self.f.subscriptions["SUB_old"]
        sub["most_recent_invoice"] = {
            "id": 501, "domain": "live", "invoice_code": "INV_retiredRestart", "subscription": 12,
            "customer": 9, "amount": 3500, "currency": "ZAR", "paid": True, "status": "success", "transaction": 444,
            "period_start": start.isoformat(), "period_end": _one_month_after(start).isoformat(),
        }
        self.f.charges["old-restart-debit"] = {**self.f.charge(self.f.old, start, 444), "reference": "old-restart-debit"}
        receipt = PaystackWebhookReceipt.objects.create(mode="live", event_type="invoice.update", payload_sha256="retired-restart-invoice", snapshot={
            "schema_version": 1, "domain": "live", "invoice_code": "INV_retiredRestart", "subscription_code": "SUB_old",
            "transaction_reference": "old-restart-debit", "transaction_id": 444,
        })
        result = process_live_payment_receipt(receipt.pk)
        self.assertEqual(result.last_result, "retired_payment_refund_queued")
        refund = StudyRefund.objects.get(reason="retired_subscription")
        self.assertEqual(process_live_refund(refund.pk).status, "processing")
        self.member.refresh_from_db()
        self.assertEqual((self.member.tier, self.member.paid_until), ("bloom", selected_end))
        self.assertEqual(self.f.subscriptions["SUB_new"]["status"], "active")

    def test_missing_new_checkout_invoice_link_does_not_attach_an_unproven_subscription(self):
        self.expire()
        payment = self.restart()
        self.pay(payment)
        self.f.subscriptions["SUB_new"]["invoices"] = []
        receipt = PaystackWebhookReceipt.objects.create(mode="live", event_type="subscription.create", payload_sha256="missing-restart-link", snapshot={
            "schema_version": 1, "domain": "live", "subscription_code": "SUB_new",
        })
        result = process_live_subscription_receipt(receipt.pk)
        self.assertEqual((result.processing_status, result.last_result), ("retry", "awaiting_exact_restart_subscription_link"))
        self.member.refresh_from_db()
        self.assertIsNone(self.member.paystack_subscription_code)

    def test_restored_refunded_history_does_not_unlock_default_payment_proof(self):
        self.expire(refunded=True)
        self.restart("grow")
        self.assertIsNone(membership_payment(self.member))
        self.assertEqual(get_study_tier(self.user), "free")

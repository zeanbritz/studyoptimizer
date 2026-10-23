"""Discard/replacement and late-payment recovery. Real network is forbidden."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from . import test_live_payments as fixtures
from .access import get_study_tier
from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment, StudyRefund
from .payment_service import CheckoutNotAllowed
from .payment_webhooks import process_live_payment_receipt
from .paystack_checkout import initialize_live_checkout, verify_live_checkout
from .paystack_client import PaystackError, PaystackLiveClient
from .refund_service import process_live_refund, request_first_payment_refund
from .subscription_webhooks import process_live_subscription_receipt


@override_settings(**{**fixtures.LIVE, "PAYSTACK_LIVE_REFUNDS_ENABLED": True})
class DiscardedCheckoutTests(TestCase):
    start = fixtures.LiveCheckoutTests.start
    successful = fixtures.LiveCheckoutTests.successful
    confirm = fixtures.LiveCheckoutTests.confirm

    def setUp(self):
        fixtures.LiveCheckoutTests.setUp(self)
        self.fetch.side_effect = lambda code: {
            "domain": "live", "plan_code": code, "currency": "ZAR", "interval": "monthly",
            "amount": 3500 if code == "PLN_growLive" else 9000,
        }

    def replace(self, payment, tier="grow", state="abandoned"):
        self.verify.return_value = {**self.successful(payment), "status": state}
        return initialize_live_checkout(user=self.user, tier=tier, replace_reference=payment.reference)

    def late_payment(self, *, same_tier=False, chosen_paid=True):
        old = self.start("grow" if same_tier else "bloom")
        chosen = self.replace(old)
        if chosen_paid:
            self.confirm(chosen)
            StudyMembership.objects.filter(user=self.user).update(paystack_subscription_code="SUB_chosen")
        self.late_charge = {**self.successful(old), "id": 9002}
        self.verify.return_value = self.late_charge
        old = verify_live_checkout(user=self.user, reference=old.reference)
        return old, chosen, StudyRefund.objects.get(payment=old)

    def setup_recovery(self, old, *, exact=False):
        self.subscription = {
            "domain": "live", "id": 80, "subscription_code": "SUB_discarded", "status": "active",
            "createdAt": timezone.now().isoformat(),
            "customer": {"customer_code": "CUS_liveOwner"},
            "plan": {"domain": "live", "plan_code": old.paystack_plan_code},
            "email_token": "privateDiscardToken",
            "invoices": [{"domain": "live", "subscription": 80, "transaction": 9002}] if exact else [],
        }
        self.customer = patch.object(PaystackLiveClient, "fetch_customer", return_value={
            "domain": "live", "id": 10, "customer_code": "CUS_liveOwner",
        }).start()
        self.subscriptions = patch.object(PaystackLiveClient, "list_customer_subscriptions", return_value=[self.subscription]).start()
        self.canonical = patch.object(PaystackLiveClient, "fetch_subscription", return_value=self.subscription).start()
        self.disable = patch.object(PaystackLiveClient, "disable_subscription", return_value={}).start()
        self.refund_payload = {
            "id": 333, "domain": "live", "transaction": 9002, "amount": old.expected_amount_cents,
            "currency": "ZAR", "status": "pending",
        }
        self.create_refund = patch.object(PaystackLiveClient, "create_full_refund", return_value=self.refund_payload).start()
        self.fetch_refund = patch.object(PaystackLiveClient, "fetch_refund", return_value=self.refund_payload).start()
        self.list_refunds = patch.object(PaystackLiveClient, "list_refunds", return_value=[]).start()

    def process(self, refund):
        StudyRefund.objects.filter(pk=refund.pk).update(next_attempt_at=None)
        return process_live_refund(refund.pk)

    def test_replacing_unpaid_bloom_opens_grow_and_retains_audit_record(self):
        old = self.start("bloom")
        chosen = self.replace(old)
        old.refresh_from_db()
        self.assertIsNotNone(old.discarded_at)
        self.assertEqual(old.status, "abandoned")
        self.assertNotEqual(old.reference, chosen.reference)
        self.assertEqual(chosen.tier, "grow")
        self.assertEqual(StudyPayment.objects.count(), 2)
        self.assertFalse(StudyMembership.objects.exists())
        self.assertFalse(StudyRefund.objects.exists())

    def test_same_tier_can_be_replaced_but_double_post_resumes_replacement(self):
        old = self.start()
        chosen = self.replace(old)
        self.verify.reset_mock()
        again = initialize_live_checkout(user=self.user, tier="grow", replace_reference=old.reference)
        self.assertEqual(again.pk, chosen.pk)
        self.assertEqual(StudyPayment.objects.count(), 2)
        self.assertEqual(self.initialize.call_count, 2)
        self.verify.assert_not_called()

    def test_other_tier_stale_form_does_not_discard_newer_checkout(self):
        old = self.start("bloom")
        chosen = self.replace(old)
        with self.assertRaises(CheckoutNotAllowed):
            initialize_live_checkout(user=self.user, tier="bloom", replace_reference=old.reference)
        chosen.refresh_from_db()
        self.assertIsNone(chosen.discarded_at)
        self.assertEqual(StudyPayment.objects.count(), 2)

    def test_processing_or_unverifiable_payment_is_not_replaced(self):
        old = self.start("bloom")
        for state in ("processing", "ongoing", "queued"):
            with self.subTest(state=state), self.assertRaises(CheckoutNotAllowed):
                self.replace(old, state=state)
        self.verify.side_effect = PaystackError("Timeout")
        with self.assertRaises(PaystackError):
            initialize_live_checkout(user=self.user, tier="grow", replace_reference=old.reference)
        old.refresh_from_db()
        self.assertIsNone(old.discarded_at)
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_already_paid_previous_checkout_activates_without_another_charge(self):
        old = self.start("bloom")
        result = self.replace(old, state="success")
        self.assertEqual(result.pk, old.pk)
        self.assertEqual(result.status, "succeeded")
        self.assertIsNone(result.discarded_at)
        self.assertEqual(get_study_tier(self.user), "bloom")
        self.initialize.assert_called_once()

    def test_tampered_paid_amount_does_not_discard_or_open_another_checkout(self):
        old = self.start("bloom")
        self.verify.return_value = {**self.successful(old), "amount": 1}
        with self.assertRaises(PaystackError):
            initialize_live_checkout(user=self.user, tier="grow", replace_reference=old.reference)
        old.refresh_from_db()
        self.assertIsNone(old.discarded_at)
        self.initialize.assert_called_once()

    def test_invalid_tier_does_not_retire_anything(self):
        old = self.start()
        with self.assertRaises(CheckoutNotAllowed):
            initialize_live_checkout(user=self.user, tier="free", replace_reference=old.reference)
        old.refresh_from_db()
        self.assertIsNone(old.discarded_at)

    def test_profile_and_pricing_name_the_checkout_being_replaced(self):
        old = self.start("bloom")
        for name in ("pricing", "my_plan"):
            page = self.client.get(reverse(name), secure=True)
            self.assertContains(page, f'name="replace_reference" value="{old.reference}"', count=2)
            self.assertContains(page, "will be replaced when you choose a plan")
            self.assertNotContains(page, "before making another payment")
        old.refresh_from_db()
        self.assertIsNone(old.discarded_at)
        self.verify.assert_not_called()

    def test_post_replaces_and_redirects_directly_to_provider(self):
        old = self.start("bloom")
        self.verify.return_value = {**self.successful(old), "status": "abandoned"}
        response = self.client.post(reverse("start_live_checkout"), {
            "tier": "grow", "replace_reference": old.reference, "confirm_subscription": "yes",
        }, secure=True)
        self.assertRedirects(response, "https://checkout.paystack.com/liveContract", fetch_redirect_response=False)
        old.refresh_from_db()
        self.assertIsNotNone(old.discarded_at)

    def test_late_old_payment_queues_one_refund_without_overwriting_chosen_access(self):
        old, chosen, refund = self.late_payment()
        member = StudyMembership.objects.get(user=self.user)
        self.assertEqual((member.tier, member.status, member.paystack_subscription_code), ("grow", "active", "SUB_chosen"))
        self.assertEqual((refund.reason, refund.amount_cents), ("discarded_checkout", 9000))
        self.assertEqual(verify_live_checkout(user=self.user, reference=old.reference).pk, old.pk)
        self.assertEqual(StudyRefund.objects.count(), 1)
        self.assertIsNone(StudyPayment.objects.get(pk=chosen.pk).discarded_at)

    def test_discarded_payment_before_new_payment_never_grants_access_or_blocks_purchase(self):
        old, chosen, refund = self.late_payment(chosen_paid=False)
        self.assertEqual(get_study_tier(self.user), "free")
        self.assertFalse(StudyMembership.objects.exists())
        self.confirm(chosen)
        self.assertEqual(get_study_tier(self.user), "grow")

    def test_full_refund_cancels_only_old_bloom_and_preserves_chosen_grow(self):
        old, chosen, refund = self.late_payment()
        before = StudyMembership.objects.filter(user=self.user).values().get()
        self.setup_recovery(old)
        result = self.process(refund)
        self.assertEqual(result.status, "processing")
        self.disable.assert_called_once_with("SUB_discarded", "privateDiscardToken")
        self.assertEqual(self.create_refund.call_args.args[:2], (9002, 9000))
        self.refund_payload["status"] = "processed"
        result = self.process(refund)
        self.assertEqual(result.status, "completed")
        old.refresh_from_db()
        self.assertEqual(old.status, "reversed")
        self.assertEqual(before, StudyMembership.objects.filter(user=self.user).values().get())
        self.create_refund.assert_called_once()
        self.assertEqual(request_first_payment_refund(self.user).payment_id, chosen.pk)

    def test_same_tier_uses_exact_invoice_proof_not_the_current_subscription(self):
        old, chosen, refund = self.late_payment(same_tier=True)
        self.setup_recovery(old, exact=True)
        current = {**deepcopy(self.subscription), "id": 81, "subscription_code": "SUB_chosen",
                   "invoices": [{"domain": "live", "subscription": 81, "transaction": 9001}]}
        self.subscriptions.return_value = [current, self.subscription]
        self.canonical.side_effect = lambda code: current if code == "SUB_chosen" else self.subscription
        self.assertEqual(self.process(refund).status, "processing")
        self.disable.assert_called_once_with("SUB_discarded", "privateDiscardToken")
        self.assertEqual(StudyMembership.objects.get(user=self.user).status, "active")

    def test_ambiguous_same_tier_requires_attention_never_cancels_chosen_plan(self):
        old, chosen, refund = self.late_payment(same_tier=True)
        self.setup_recovery(old)
        self.assertEqual(self.process(refund).status, "approved")
        self.disable.assert_not_called()
        self.create_refund.assert_not_called()
        StudyRefund.objects.filter(pk=refund.pk).update(requested_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(self.process(refund).status, "attention")
        self.assertEqual(StudyMembership.objects.get(user=self.user).paystack_subscription_code, "SUB_chosen")

    def test_even_exact_proof_cannot_cancel_a_subscription_linked_as_current(self):
        old, chosen, refund = self.late_payment(same_tier=True)
        self.setup_recovery(old, exact=True)
        StudyMembership.objects.filter(user=self.user).update(paystack_subscription_code="SUB_discarded")
        self.assertEqual(self.process(refund).status, "attention")
        self.disable.assert_not_called()
        self.create_refund.assert_not_called()

    def test_refund_timeout_reconciles_without_repeating_financial_post(self):
        old, chosen, refund = self.late_payment()
        self.setup_recovery(old)
        self.create_refund.side_effect = PaystackError("Timeout after submission")
        self.assertEqual(self.process(refund).status, "submitting")
        self.process(refund)
        self.create_refund.assert_called_once()
        self.list_refunds.return_value = [self.refund_payload]
        self.refund_payload["status"] = "processed"
        self.assertEqual(self.process(refund).status, "completed")
        self.create_refund.assert_called_once()

    def test_old_charge_webhook_recovers_even_after_account_deactivation(self):
        old = self.start("bloom")
        self.replace(old)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.verify.return_value = {**self.successful(old), "id": 9002}
        receipt = PaystackWebhookReceipt.objects.create(
            mode="live", event_type="charge.success", payload_sha256="a" * 64,
            snapshot={"schema_version": 1, "domain": "live", "transaction_reference": old.reference},
        )
        self.assertEqual(process_live_payment_receipt(receipt.pk).processing_status, "processed")
        self.assertEqual(StudyRefund.objects.get().reason, "discarded_checkout")
        self.assertFalse(StudyMembership.objects.exists())

    def test_discarded_same_tier_subscription_event_cannot_hijack_new_membership(self):
        old, chosen, refund = self.late_payment(same_tier=True)
        self.setup_recovery(old, exact=True)
        StudyMembership.objects.filter(user=self.user).update(paystack_subscription_code=None)
        receipt = PaystackWebhookReceipt.objects.create(
            mode="live", event_type="subscription.create", payload_sha256="b" * 64,
            snapshot={"schema_version": 1, "domain": "live", "subscription_code": "SUB_discarded"},
        )
        self.assertEqual(process_live_subscription_receipt(receipt.pk).processing_status, "retry")
        self.assertIsNone(StudyMembership.objects.get(user=self.user).paystack_subscription_code)

    def test_profile_shows_separate_recovery_without_consuming_the_guarantee(self):
        old, chosen, refund = self.late_payment()
        page = self.client.get(reverse("my_plan"), secure=True)
        self.assertContains(page, "Replaced checkout refund")
        self.assertContains(page, "Check eligibility and request refund")
        self.assertNotContains(page, f'name="replace_reference" value="{old.reference}"')

    def test_recovery_continues_with_new_checkout_and_voluntary_refunds_paused(self):
        old, chosen, refund = self.late_payment()
        self.setup_recovery(old)
        with override_settings(PAYSTACK_LIVE_CHECKOUT_ENABLED=False, PAYSTACK_LIVE_REFUNDS_ENABLED=False):
            self.assertEqual(self.process(refund).status, "processing")
        self.create_refund.assert_called_once()

    def test_discarded_recovery_is_not_limited_by_the_seven_day_guarantee(self):
        old, chosen, refund = self.late_payment()
        self.setup_recovery(old)
        paid_at = timezone.now() - timedelta(days=9)
        self.late_charge["paid_at"] = paid_at.isoformat()
        StudyPayment.objects.filter(pk=old.pk).update(created_at=paid_at - timedelta(days=1))
        self.subscription["createdAt"] = paid_at.isoformat()
        self.assertEqual(self.process(refund).status, "processing")
        self.create_refund.assert_called_once()

    def test_a_contradictory_invoice_is_never_ignored_for_a_unique_match(self):
        old, chosen, refund = self.late_payment()
        self.setup_recovery(old, exact=True)
        self.subscription["invoices"][0]["transaction"] = 9999
        self.assertEqual(self.process(refund).status, "approved")
        self.disable.assert_not_called()
        self.create_refund.assert_not_called()

    def test_guarantee_once_per_account_still_enforced_separately_from_recovery(self):
        old, chosen, recovery = self.late_payment()
        guarantee = request_first_payment_refund(self.user)
        self.assertEqual(StudyRefund.objects.filter(user=self.user).count(), 2)
        self.assertNotEqual(recovery.pk, guarantee.pk)
        other = StudyPayment.objects.create(
            user=self.user, tier="grow", plan="monthly", mode="live", expected_amount_cents=3500,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudyRefund.objects.create(user=self.user, payment=other, amount_cents=3500)

    def test_replayed_charge_after_completed_refund_never_restores_paid_access(self):
        old, chosen, refund = self.late_payment(chosen_paid=False)
        self.setup_recovery(old)
        self.process(refund)
        self.refund_payload["status"] = "processed"
        self.process(refund)
        receipt = PaystackWebhookReceipt.objects.create(
            mode="live", event_type="charge.success", payload_sha256="c" * 64,
            snapshot={"schema_version": 1, "domain": "live", "transaction_reference": old.reference},
        )
        self.assertEqual(process_live_payment_receipt(receipt.pk).processing_status, "processed")
        self.assertFalse(StudyMembership.objects.exists())
        self.assertEqual(StudyRefund.objects.count(), 1)
        self.create_refund.assert_called_once()

    def test_already_paid_post_returns_to_profile_not_back_to_the_old_checkout(self):
        old = self.start("bloom")
        self.verify.return_value = self.successful(old)
        response = self.client.post(reverse("start_live_checkout"), {
            "tier": "grow", "replace_reference": old.reference, "confirm_subscription": "yes",
        }, secure=True)
        self.assertRedirects(response, reverse("my_plan"), fetch_redirect_response=False)
        self.assertEqual(get_study_tier(self.user), "bloom")
        self.initialize.assert_called_once()

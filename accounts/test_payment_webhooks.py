"""Renewals and failed invoices; no real keys, charges, or provider writes."""

import hashlib
import hmac
import io
import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .access import get_study_tier
from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment, StudyTier
from .payment_webhooks import process_test_payment_receipt
from .paystack_checkout import _one_month_after
from .paystack_client import PaystackError, PaystackTestClient
from .test_paystack_checkout import SANDBOX


COMMAND = "accounts.management.commands.process_paystack_test_payments"


@override_settings(**SANDBOX)
class PaymentWebhookTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="renewal-student", email="student@example.com")
        self.start = timezone.now().replace(microsecond=0) - timedelta(days=10)
        self.end = _one_month_after(self.start)
        self.initial = StudyPayment.objects.create(
            user=self.user, tier="grow", plan="monthly", mode="test", status="succeeded",
            expected_amount_cents=3500, currency="ZAR", paystack_plan_code="PLN_original",
            checkout_email=self.user.email, paystack_transaction_id=101, verified_at=self.start - timedelta(days=30),
        )
        StudyPayment.objects.filter(pk=self.initial.pk).update(created_at=self.start - timedelta(days=31))
        self.initial.refresh_from_db()
        self.member = StudyMembership.objects.create(
            user=self.user, tier="grow", plan="monthly", payment_mode="test", status="active",
            paid_until=self.start, paystack_customer_code="CUS_owner", paystack_subscription_code="SUB_owner",
        )
        self.invoice = {
            "id": 33, "domain": "test", "invoice_code": "INV_current", "amount": 3500,
            "subscription": 11, "customer": 9, "transaction": 202, "status": "success", "paid": 1,
            "period_start": self.start.isoformat(), "period_end": self.end.isoformat(),
        }
        self.subscription = {
            "id": 11, "domain": "test", "subscription_code": "SUB_owner", "status": "active",
            "customer": {"id": 9, "customer_code": "CUS_owner"},
            "plan": {"domain": "test", "plan_code": "PLN_original"},
            "createdAt": self.initial.created_at.isoformat(), "most_recent_invoice": self.invoice,
            "email_token": "privateCancellationToken",
        }
        self.charge = {
            "id": 202, "reference": "renewal-" + "x" * 65, "domain": "test", "status": "success",
            "amount": 3500, "currency": "ZAR", "paid_at": self.start.isoformat(),
            "customer": {"id": 9, "customer_code": "CUS_owner", "email": self.user.email},
            "plan": "PLN_original", "plan_object": {"plan_code": "PLN_original"},
            "authorization": {"authorization_code": "AUTH_private"},
        }
        self.snapshot = {
            "schema_version": 1, "domain": "test", "invoice_code": "INV_current",
            "subscription_code": "SUB_owner", "customer_code": "CUS_owner", "plan_code": "PLN_original",
            "amount_cents": 3500, "currency": "ZAR", "period_start": self.start.isoformat(),
            "period_end": self.end.isoformat(), "transaction_reference": self.charge["reference"], "transaction_id": 202,
        }
        self.fetch = patch.object(PaystackTestClient, "fetch_subscription", return_value=self.subscription).start()
        self.verify = patch.object(PaystackTestClient, "verify", return_value=self.charge).start()
        self.network = patch.object(PaystackTestClient, "_request", side_effect=AssertionError("Unexpected provider request")).start()
        self.addCleanup(patch.stopall)

    def receipt(self, event="invoice.update", **changes):
        snapshot = deepcopy(self.snapshot)
        snapshot.update(changes)
        return PaystackWebhookReceipt.objects.create(
            mode="test", event_type=event, snapshot=snapshot,
            payload_sha256=hashlib.sha256(str(PaystackWebhookReceipt.objects.count()).encode()).hexdigest(),
        )

    def process(self, receipt=None):
        return process_test_payment_receipt((receipt or self.receipt()).pk)

    def failure(self):
        self.invoice.update(status="failed", paid=0, transaction=None)
        self.subscription["status"] = "attention"

    def assert_unchanged(self):
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, "active")
        self.assertEqual(self.member.paid_until, self.start)
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_verified_invoice_grants_absolute_period_and_stores_only_billing_identifiers(self):
        result = self.process()
        self.member.refresh_from_db()
        payment = StudyPayment.objects.get(source="renewal")
        self.assertEqual(result.last_result, "renewal_verified")
        self.assertEqual(result.processing_status, "processed")
        self.assertEqual(self.member.paid_until, self.end)
        self.assertEqual(self.member.status, "active")
        self.assertEqual(get_study_tier(self.user), StudyTier.GROW)
        self.assertEqual(payment.reference, self.charge["reference"])
        self.assertEqual(payment.paystack_transaction_id, 202)
        self.assertEqual(payment.paystack_invoice_code, "INV_current")
        self.assertEqual(payment.paystack_subscription_code, "SUB_owner")
        self.assertEqual(payment.period_start, self.start)
        self.assertEqual(payment.period_end, self.end)
        self.assertEqual(payment.expected_amount_cents, 3500)
        self.assertIsNotNone(payment.verified_at)
        stored = json.dumps(list(StudyPayment.objects.values()), default=str)
        self.assertNotIn("AUTH_private", stored)
        self.assertNotIn("privateCancellationToken", stored)
        self.network.assert_not_called()

    def test_exact_and_changed_body_redelivery_cannot_stack_access(self):
        receipt = self.receipt()
        self.process(receipt)
        self.process(receipt)
        self.fetch.assert_called_once()
        self.verify.assert_called_once()
        again = self.process(self.receipt(paid=True))
        self.assertEqual(again.last_result, "payment_already_recorded")
        self.member.refresh_from_db()
        self.assertEqual(self.member.paid_until, self.end)
        self.assertEqual(StudyPayment.objects.filter(source="renewal").count(), 1)

    def test_bloom_renewal_uses_original_90_rand_snapshot(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(tier="bloom")
        StudyPayment.objects.filter(pk=self.initial.pk).update(tier="bloom", expected_amount_cents=9000)
        self.invoice["amount"] = 9000
        self.charge["amount"] = 9000
        result = self.process(self.receipt(amount_cents=9000))
        self.assertEqual(result.last_result, "renewal_verified")
        self.assertEqual(get_study_tier(self.user), StudyTier.BLOOM)
        self.assertEqual(StudyPayment.objects.get(source="renewal").expected_amount_cents, 9000)

    def test_verified_invoice_can_link_subscription_before_metadata_notification_arrives(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(paystack_subscription_code=None)
        self.process()
        self.member.refresh_from_db()
        self.assertEqual(self.member.paystack_subscription_code, "SUB_owner")
        self.assertEqual(self.member.paid_until, self.end)

    def test_unknown_charge_waits_for_invoice_then_is_acknowledged_without_second_credit(self):
        charge = self.receipt(event="charge.success")
        result = self.process(charge)
        self.assertEqual(result.last_result, "awaiting_verified_invoice")
        self.fetch.assert_not_called()
        self.verify.assert_not_called()
        self.assert_unchanged()
        self.process()
        PaystackWebhookReceipt.objects.filter(pk=charge.pk).update(next_attempt_at=None)
        result = self.process(charge)
        self.assertEqual(result.last_result, "payment_already_recorded")
        self.assertEqual(StudyPayment.objects.count(), 2)

    def test_initial_checkout_can_be_verified_when_browser_never_returns(self):
        self.member.delete()
        StudyPayment.objects.filter(pk=self.initial.pk).update(status="pending", verified_at=None, paystack_transaction_id=None)
        self.charge.update(id=101, reference=self.initial.reference, paid_at=self.initial.created_at.isoformat())
        self.process(self.receipt(event="charge.success", transaction_reference=self.initial.reference, transaction_id=101))
        self.initial.refresh_from_db()
        self.assertEqual(self.initial.status, "succeeded")
        self.assertEqual(StudyPayment.objects.count(), 1)
        self.assertEqual(StudyMembership.objects.get(user=self.user).payment_mode, "test")
        self.fetch.assert_not_called()

    def test_original_checkout_transaction_never_credits_another_month(self):
        self.charge.update(id=101, reference=self.initial.reference)
        self.invoice["transaction"] = 101
        result = self.process(self.receipt(transaction_reference=self.initial.reference, transaction_id=101))
        self.assertEqual(result.last_result, "payment_already_recorded")
        self.assert_unchanged()

    def test_two_invoices_cannot_claim_the_same_transaction(self):
        self.process()
        self.invoice["invoice_code"] = "INV_other"
        result = self.process(self.receipt(invoice_code="INV_other"))
        self.assertEqual(result.processing_status, "ignored")
        self.assertEqual(result.last_result, "transaction_already_owned")
        self.assertEqual(StudyPayment.objects.count(), 2)

    def test_invoice_cannot_be_reassigned_a_different_transaction(self):
        self.process()
        self.charge.update(id=203, reference="another-transaction")
        self.invoice["transaction"] = 203
        result = self.process(self.receipt(transaction_reference="another-transaction", transaction_id=203))
        self.assertEqual(result.last_result, "invoice_transaction_conflict")
        self.assertEqual(StudyPayment.objects.count(), 2)

    def test_invoice_unique_constraint_is_enforced_by_database(self):
        self.process()
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudyPayment.objects.create(user=self.user, tier="grow", plan="monthly", mode="test", expected_amount_cents=3500, paystack_invoice_code="INV_current")

    def test_failed_invoice_preserves_paid_time_and_does_not_grant_grace(self):
        self.failure()
        self.process(self.receipt(event="invoice.payment_failed"))
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, "past_due")
        self.assertEqual(self.member.paid_until, self.start)
        self.assertIsNone(self.member.grace_until)
        self.assertEqual(get_study_tier(self.user), StudyTier.FREE)
        payment = StudyPayment.objects.get(source="renewal")
        self.assertEqual(payment.status, "failed")
        self.assertIsNone(payment.verified_at)
        self.assertIsNone(payment.paystack_transaction_id)
        self.verify.assert_not_called()

    def test_failure_keeps_unexpired_paid_access_and_existing_grace_unchanged(self):
        until, grace = timezone.now() + timedelta(days=1), timezone.now() + timedelta(days=2)
        StudyMembership.objects.filter(pk=self.member.pk).update(paid_until=until, grace_until=grace)
        self.failure()
        self.process()
        self.member.refresh_from_db()
        self.assertEqual(self.member.paid_until, until)
        self.assertEqual(self.member.grace_until, grace)
        self.assertEqual(get_study_tier(self.user), StudyTier.GROW)

    def test_failure_does_not_remove_saved_data_or_beta_access(self):
        from learning.models import Subject
        subject = Subject.objects.create(user=self.user, name="Biology")
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        self.failure()
        self.process()
        self.user.refresh_from_db()
        self.assertTrue(self.user.beta_lifetime_access)
        self.assertEqual(get_study_tier(self.user), StudyTier.BLOOM)
        self.assertTrue(Subject.objects.filter(pk=subject.pk).exists())

    def test_failed_then_successful_invoice_updates_one_record_once(self):
        self.failure()
        self.process(self.receipt(event="invoice.payment_failed"))
        self.invoice.update(status="success", paid=True, transaction=202)
        self.subscription["status"] = "active"
        self.process()
        self.assertEqual(StudyPayment.objects.filter(source="renewal").count(), 1)
        self.assertEqual(StudyPayment.objects.get(source="renewal").status, "succeeded")
        self.member.refresh_from_db()
        self.assertEqual(self.member.paid_until, self.end)
        self.assertEqual(self.member.status, "active")

    def test_delayed_failure_cannot_undo_success_for_same_invoice(self):
        self.process()
        self.failure()
        self.process(self.receipt(event="invoice.payment_failed"))
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, "active")
        self.assertEqual(self.member.paid_until, self.end)
        self.assertEqual(StudyPayment.objects.get(source="renewal").status, "succeeded")

    def test_stale_failure_cannot_undo_later_paid_period(self):
        later = self.end + timedelta(days=30)
        StudyMembership.objects.filter(pk=self.member.pk).update(paid_until=later)
        self.failure()
        self.process()
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, "active")
        self.assertEqual(self.member.paid_until, later)

    def test_old_success_cannot_hide_newer_failed_invoice(self):
        StudyPayment.objects.create(
            user=self.user, tier="grow", plan="monthly", mode="test", source="renewal", status="failed", expected_amount_cents=3500,
            paystack_subscription_code="SUB_owner", paystack_invoice_code="INV_later", period_start=self.end, period_end=self.end + timedelta(days=30),
        )
        self.process()
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, "past_due")
        self.assertEqual(self.member.paid_until, self.end)

    def test_success_does_not_restart_cancelled_future_renewals(self):
        for provider in ("active", "non-renewing", "cancelled", "complete"):
            StudyMembership.objects.filter(pk=self.member.pk).update(status="non_renewing")
            self.subscription["status"] = provider
            self.process()
            self.member.refresh_from_db()
            self.assertEqual(self.member.status, "non_renewing")
            self.assertEqual(self.member.paid_until, self.end)

    def test_failure_does_not_restart_cancelled_future_renewals(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(status="non_renewing")
        self.failure()
        self.process()
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, "non_renewing")
        self.assertEqual(self.member.paid_until, self.start)

    def test_verified_payment_does_not_reactivate_inactive_user(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(status="expired")
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.process()
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertIsNone(get_study_tier(self.user))

    def test_missing_current_invoice_or_transaction_waits_without_verifying_arbitrary_charge(self):
        self.subscription["most_recent_invoice"] = None
        self.assertEqual(self.process().last_result, "provider_invoice_unavailable")
        self.subscription["most_recent_invoice"] = self.invoice
        self.invoice.pop("transaction")
        self.assertEqual(self.process().last_result, "invoice_transaction_unconfirmed")
        self.verify.assert_not_called()
        self.assert_unchanged()

    def test_wrong_mode_owner_plan_or_invoice_price_cannot_grant_access(self):
        for path, value in (
            (("domain",), "live"), (("customer", "customer_code"), "CUS_other"),
            (("plan", "plan_code"), "PLN_other"), (("most_recent_invoice", "domain"), "live"),
            (("most_recent_invoice", "amount"), 9000), (("most_recent_invoice", "customer"), 77),
            (("most_recent_invoice", "subscription"), 88),
        ):
            response = deepcopy(self.subscription)
            target = response
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            self.fetch.return_value = response
            self.assertIn(self.process().processing_status, ("ignored", "retry"))
            self.assert_unchanged()

    def test_transaction_validates_price_mode_owner_plan_reference_and_integer_id(self):
        for field, value in (
            ("amount", 35), ("amount", True), ("currency", "USD"), ("domain", "live"),
            ("reference", "foreign-charge"), ("id", True), ("id", 900),
            ("customer", {"customer_code": "CUS_other", "email": self.user.email}),
            ("customer", {"customer_code": "CUS_owner", "email": "foreign@example.com"}),
            ("plan", "PLN_other"), ("plan_object", {"domain": "live", "plan_code": "PLN_original"}),
        ):
            response = deepcopy(self.charge)
            response[field] = value
            self.verify.return_value = response
            self.assertIn(self.process().processing_status, ("ignored", "retry"))
            self.assert_unchanged()

    def test_pending_failed_transaction_and_invalid_paid_times_never_grant_access(self):
        for field, value in (
            ("status", "pending"), ("status", "failed"), ("paid_at", None),
            ("paid_at", (timezone.now() + timedelta(days=1)).isoformat()),
            ("paid_at", (self.start - timedelta(days=2)).isoformat()),
        ):
            response = deepcopy(self.charge)
            response[field] = value
            self.verify.return_value = response
            self.assertEqual(self.process().processing_status, "retry")
            self.assert_unchanged()

    def test_invalid_overlong_reversed_or_future_invoice_period_is_not_credited(self):
        for start, end in (
            (self.start, self.start - timedelta(seconds=1)),
            (self.start, self.start + timedelta(days=365)),
            (timezone.now() + timedelta(days=2), timezone.now() + timedelta(days=32)),
            (self.start.replace(tzinfo=None), self.end.replace(tzinfo=None)),
        ):
            self.invoice.update(period_start=start.isoformat(), period_end=end.isoformat())
            self.assertEqual(self.process().processing_status, "retry")
            self.assert_unchanged()

    def test_signed_period_must_match_provider_invoice(self):
        result = self.process(self.receipt(period_end=(self.end + timedelta(days=1)).isoformat()))
        self.assertEqual(result.last_result, "invoice_period_mismatch")
        self.assert_unchanged()

    def test_signed_invoice_id_must_match_provider_invoice(self):
        result = self.process(self.receipt(object_id=99))
        self.assertEqual(result.last_result, "invoice_identity_mismatch")
        self.assert_unchanged()

    def test_unconfirmed_or_conflicting_failure_status_does_not_change_paid_access(self):
        self.failure()
        self.subscription["status"] = "active"
        self.assertEqual(self.process().last_result, "failure_not_current")
        self.subscription["status"] = "attention"
        for paid, status in (("false", "failed"), (True, "failed"), (0, "success")):
            self.invoice.update(paid=paid, status=status)
            self.assertEqual(self.process().last_result, "invoice_state_unconfirmed")
        self.assert_unchanged()

    def test_provider_failure_retries_with_backoff_and_no_secret_text(self):
        self.verify.side_effect = PaystackError("sk_test_private privateCancellationToken")
        receipt = self.receipt()
        result = self.process(receipt)
        self.assertEqual(result.last_result, "provider_unavailable")
        self.assertGreater(result.next_attempt_at, timezone.now())
        self.assertIsNone(result.processed_at)
        self.process(receipt)
        self.verify.assert_called_once()
        self.assertNotIn("private", result.last_result)
        self.assert_unchanged()

    def test_live_membership_and_foreign_subscription_cannot_be_overwritten(self):
        for changes in ({"payment_mode": "live"}, {"paystack_subscription_code": "SUB_other"}):
            StudyMembership.objects.filter(pk=self.member.pk).update(**changes)
            before = list(StudyMembership.objects.values())
            self.process()
            self.assertEqual(list(StudyMembership.objects.values()), before)
            self.assertEqual(StudyPayment.objects.count(), 1)

    def test_missing_initial_checkout_proof_waits_without_guessing_from_email(self):
        StudyPayment.objects.filter(pk=self.initial.pk).update(verified_at=None)
        self.assertEqual(self.process().processing_status, "retry")
        self.assert_unchanged()

    def test_invoice_create_is_only_schedule_metadata_without_provider_calls(self):
        self.assertEqual(self.process(self.receipt(event="invoice.create")).last_result, "invoice_scheduled")
        self.fetch.assert_not_called()
        self.verify.assert_not_called()
        self.assert_unchanged()

    def test_signed_http_capture_then_processor_uses_canonical_invoice_and_verified_charge(self):
        data = deepcopy(self.invoice)
        data["subscription"] = {"id": 11, "subscription_code": "SUB_owner"}
        data["customer"] = {"id": 9, "customer_code": "CUS_owner", "email": self.user.email}
        data["transaction"] = deepcopy(self.charge)
        body = json.dumps({"event": "invoice.update", "data": data}).encode()
        signature = hmac.new(SANDBOX["PAYSTACK_TEST_SECRET_KEY"].encode(), body, hashlib.sha512).hexdigest()
        response = Client(enforce_csrf_checks=True, HTTP_HOST="localhost").post(
            reverse("paystack_test_webhook"), data=body, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, 200)
        receipt = PaystackWebhookReceipt.objects.get()
        self.assertEqual(self.process(receipt).last_result, "renewal_verified")
        self.network.assert_not_called()

    def test_debug_flag_and_live_key_gates_fail_before_network_or_updates(self):
        receipt = self.receipt()
        for changes in ({"DEBUG": False}, {"PAYSTACK_TEST_CHECKOUT_ENABLED": False}, {"PAYSTACK_TEST_SECRET_KEY": "sk_live_dummy"}):
            with self.settings(**changes), self.assertRaises(PaystackError):
                self.process(receipt)
        self.fetch.assert_not_called()
        self.assert_unchanged()

    def test_invalid_ids_modes_events_and_snapshots_do_not_process(self):
        for receipt_id in (True, None, 0, "1"):
            with self.assertRaises(ValueError):
                process_test_payment_receipt(receipt_id)
        for changes in ({"mode": "live"}, {"event_type": "subscription.create"}):
            receipt = self.receipt()
            PaystackWebhookReceipt.objects.filter(pk=receipt.pk).update(**changes)
            with self.assertRaises(ValueError):
                self.process(receipt)
        for changes in ({"schema_version": True}, {"domain": "live"}, {"invoice_code": "bad"}, {"subscription_code": None}):
            self.assertEqual(self.process(self.receipt(**changes)).processing_status, "ignored")
        self.fetch.assert_not_called()
        self.assert_unchanged()

    def test_local_batch_is_guarded_bounded_and_does_not_expose_secrets(self):
        self.receipt()
        output = io.StringIO()
        with patch(COMMAND + "._require_disposable_preview"):
            call_command("process_paystack_test_payments", stdout=output, limit=1)
            with self.assertRaises(CommandError):
                call_command("process_paystack_test_payments", stdout=io.StringIO(), limit=101)
        self.assertIn("processed (renewal_verified)", output.getvalue())
        self.assertNotIn(self.user.email, output.getvalue())
        self.assertNotIn("privateCancellationToken", output.getvalue())
        with patch(COMMAND + "._require_disposable_preview", side_effect=CommandError("wrong DB")):
            with self.assertRaises(CommandError):
                call_command("process_paystack_test_payments", stdout=io.StringIO())

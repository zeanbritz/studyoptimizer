"""Live notifications and background processing, with no real network calls."""

import hashlib
import hmac
import io
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .access import get_study_tier
from .management.commands.process_paystack_live_events import process_batch
from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment
from .payment_webhooks import process_live_payment_receipt, process_test_payment_receipt
from .paystack_checkout import _one_month_after
from .paystack_client import PaystackLiveClient, PaystackError
from .subscription_webhooks import process_live_subscription_receipt
from .test_live_payments import LIVE


@override_settings(**LIVE)
class LiveWebhookTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="live-renewal", email="owner@example.com")
        self.start = timezone.now().replace(microsecond=0) - timedelta(days=1)
        self.end = _one_month_after(self.start)
        self.initial = StudyPayment.objects.create(
            user=self.user, mode="live", tier="grow", plan="monthly", status="succeeded",
            expected_amount_cents=3500, paystack_plan_code="PLN_growLive", checkout_email=self.user.email,
            paystack_transaction_id=1001, verified_at=self.start - timedelta(days=30),
        )
        StudyPayment.objects.filter(pk=self.initial.pk).update(created_at=self.start - timedelta(days=31))
        self.member = StudyMembership.objects.create(
            user=self.user, payment_mode="live", tier="grow", plan="monthly", status="active",
            paid_until=self.start, paystack_customer_code="CUS_owner", paystack_subscription_code="SUB_owner",
        )
        self.invoice = {
            "domain": "live", "id": 33, "invoice_code": "INV_current", "amount": 3500,
            "subscription": 11, "customer": 9, "transaction": 1002, "status": "success", "paid": True,
            "period_start": self.start.isoformat(), "period_end": self.end.isoformat(),
        }
        self.subscription = {
            "domain": "live", "id": 11, "subscription_code": "SUB_owner", "status": "active",
            "customer": {"id": 9, "customer_code": "CUS_owner"},
            "plan": {"domain": "live", "plan_code": "PLN_growLive"},
            "createdAt": self.initial.created_at.isoformat(), "most_recent_invoice": self.invoice,
        }
        self.charge = {
            "domain": "live", "id": 1002, "reference": "renewal-live-contract", "status": "success",
            "amount": 3500, "currency": "ZAR", "paid_at": self.start.isoformat(),
            "customer": {"id": 9, "customer_code": "CUS_owner", "email": self.user.email},
            "plan": "PLN_growLive",
        }
        self.snapshot = {
            "schema_version": 1, "domain": "live", "subscription_code": "SUB_owner", "invoice_code": "INV_current",
            "customer_code": "CUS_owner", "plan_code": "PLN_growLive", "transaction_id": 1002,
            "transaction_reference": "renewal-live-contract", "period_start": self.start.isoformat(),
            "period_end": self.end.isoformat(), "amount_cents": 3500, "currency": "ZAR",
        }
        self.fetch = patch.object(PaystackLiveClient, "fetch_subscription", return_value=self.subscription).start()
        self.verify = patch.object(PaystackLiveClient, "verify", return_value=self.charge).start()
        self.network = patch("accounts.paystack_client.build_opener", side_effect=AssertionError("Real network forbidden")).start()
        self.addCleanup(patch.stopall)
        self.client = Client(enforce_csrf_checks=True, HTTP_HOST="studigarden.com")

    def receipt(self, event="invoice.update", **changes):
        return PaystackWebhookReceipt.objects.create(
            mode="live", event_type=event, snapshot={**self.snapshot, **changes},
            payload_sha256=hashlib.sha256(str(PaystackWebhookReceipt.objects.count()).encode()).hexdigest(),
        )

    def signed_post(self, mode="live", key=None, **extra):
        data = {**self.invoice, "domain": mode, "subscription": self.subscription, "transaction": self.charge,
                "email_token": "privateToken", "authorization": {"last4": "privateCard"}}
        raw = json.dumps({"event": "invoice.update", "data": data}).encode()
        signature = hmac.new((key or LIVE["PAYSTACK_LIVE_SECRET_KEY"]).encode(), raw, hashlib.sha512).hexdigest()
        return self.client.post(reverse("paystack_live_webhook"), raw, content_type="application/json",
                                HTTP_X_PAYSTACK_SIGNATURE=signature, secure=True, **extra)

    def test_live_signature_is_captured_without_network_or_immediate_access(self):
        response = self.signed_post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.signed_post().json()["duplicate"], True)
        receipt = PaystackWebhookReceipt.objects.get()
        self.assertEqual((receipt.mode, receipt.processing_status), ("live", "received"))
        self.assertNotIn("privateToken", json.dumps(receipt.snapshot))
        self.assertNotIn("privateCard", json.dumps(receipt.snapshot))
        self.assertEqual(get_study_tier(self.user), "free")
        self.network.assert_not_called()
        self.fetch.assert_not_called()
        self.verify.assert_not_called()

    def test_test_key_or_signed_test_domain_cannot_enter_live_inbox(self):
        self.assertEqual(self.signed_post(key=LIVE["PAYSTACK_TEST_SECRET_KEY"]).status_code, 403)
        self.assertEqual(self.signed_post(mode="test").status_code, 400)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_live_inbox_is_hidden_without_production_configuration(self):
        with override_settings(DEBUG=True):
            self.assertEqual(self.signed_post().status_code, 404)
        with override_settings(PAYSTACK_LIVE_ENABLED=False):
            self.assertEqual(self.signed_post().status_code, 404)
        self.assertEqual(self.signed_post(HTTP_HOST="localhost").status_code, 404)

    def test_verified_live_renewal_grants_absolute_period_once(self):
        receipt = self.receipt()
        result = process_live_payment_receipt(receipt.pk)
        self.assertEqual(result.last_result, "renewal_verified")
        self.member.refresh_from_db()
        self.assertEqual(self.member.paid_until, self.end)
        self.assertEqual(get_study_tier(self.user), "grow")
        self.assertEqual(StudyPayment.objects.get(source="renewal").mode, "live")
        process_live_payment_receipt(receipt.pk)
        self.fetch.assert_called_once()
        self.verify.assert_called_once()
        self.assertEqual(StudyPayment.objects.count(), 2)

    def test_live_receipt_cannot_change_test_membership(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(payment_mode="test")
        result = process_live_payment_receipt(self.receipt().pk)
        self.assertEqual(result.processing_status, "ignored")
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_live_processor_refuses_test_receipts(self):
        receipt = self.receipt()
        PaystackWebhookReceipt.objects.filter(pk=receipt.pk).update(mode="test")
        with self.assertRaises(ValueError):
            process_live_payment_receipt(receipt.pk)
        self.fetch.assert_not_called()

    def test_verified_test_charge_cannot_credit_live_renewal(self):
        self.charge["domain"] = "test"
        result = process_live_payment_receipt(self.receipt().pk)
        self.assertEqual(result.processing_status, "ignored")
        self.assertEqual(StudyPayment.objects.count(), 1)
        self.assertEqual(get_study_tier(self.user), "free")

    def test_failure_does_not_delete_paid_time_or_invent_grace(self):
        self.invoice.update(status="failed", paid=False, transaction=None)
        self.subscription["status"] = "attention"
        result = process_live_payment_receipt(self.receipt(event="invoice.payment_failed").pk)
        self.member.refresh_from_db()
        self.assertEqual(result.last_result, "renewal_failed")
        self.assertEqual(self.member.status, "past_due")
        self.assertEqual(self.member.paid_until, self.start)
        self.assertIsNone(self.member.grace_until)
        self.verify.assert_not_called()

    def test_cancellation_notification_never_extends_paid_access(self):
        self.subscription["status"] = "non-renewing"
        receipt = self.receipt(event="subscription.not_renew")
        result = process_live_subscription_receipt(receipt.pk)
        self.member.refresh_from_db()
        self.assertEqual(result.last_result, "renewals_stopped")
        self.assertEqual(self.member.paid_until, self.start)
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_provider_timeout_is_durable_and_does_not_grant_access(self):
        self.fetch.side_effect = PaystackError("Sanitized failure")
        result = process_live_payment_receipt(self.receipt().pk)
        self.assertEqual((result.processing_status, result.last_result), ("retry", "provider_unavailable"))
        self.assertGreater(result.next_attempt_at, timezone.now())
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_batch_processes_live_due_events_not_test_future_or_terminal(self):
        receipt = self.receipt()
        test = self.receipt()
        PaystackWebhookReceipt.objects.filter(pk=test.pk).update(mode="test")
        future = self.receipt()
        PaystackWebhookReceipt.objects.filter(pk=future.pk).update(next_attempt_at=timezone.now() + timedelta(hours=1))
        terminal = self.receipt()
        PaystackWebhookReceipt.objects.filter(pk=terminal.pk).update(processing_status="processed")
        self.assertEqual(process_batch(), [(receipt.pk, "processed", "renewal_verified")])
        self.fetch.assert_called_once()

    def test_worker_runs_with_sales_paused_but_fails_closed_when_billing_disabled(self):
        self.receipt()
        with override_settings(PAYSTACK_LIVE_CHECKOUT_ENABLED=False):
            call_command("process_paystack_live_events", once=True, stdout=io.StringIO())
        self.assertEqual(get_study_tier(self.user), "grow")
        with override_settings(PAYSTACK_LIVE_ENABLED=False), self.assertRaises(CommandError):
            process_batch()

    def test_late_invoice_is_held_for_review_not_guessed(self):
        result = process_live_payment_receipt(self.receipt(invoice_code="INV_older").pk)
        self.assertEqual(result.last_result, "provider_invoice_unavailable")
        self.assertEqual(result.processing_status, "retry")
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_one_unexpected_event_error_is_held_for_review_without_crashing_worker(self):
        receipt = self.receipt()
        with patch("accounts.management.commands.process_paystack_live_events.process_live_payment_receipt",
                   side_effect=ValueError("Untrusted provider text must not be stored")):
            self.assertEqual(process_batch(), [(receipt.pk, "retry", "processor_error")])
        receipt.refresh_from_db()
        self.assertNotIn("Untrusted", receipt.last_result)
        self.assertGreater(receipt.next_attempt_at, timezone.now())

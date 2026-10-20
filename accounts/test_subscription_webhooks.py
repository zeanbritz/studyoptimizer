"""Subscription reconciliation only. All provider requests are mocked GETs."""

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
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .access import get_study_tier
from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment, StudyTier
from .paystack_client import PaystackError, PaystackTestClient
from .subscription_webhooks import process_test_subscription_receipt
from .test_paystack_checkout import SANDBOX


COMMAND_MODULE = "accounts.management.commands.process_paystack_test_subscriptions"


@override_settings(**SANDBOX)
class SubscriptionWebhookTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="webhook-student")
        self.end = timezone.now() + timedelta(days=20)
        self.member = StudyMembership.objects.create(
            user=self.user, tier="grow", plan="monthly", payment_mode="test", status="active",
            paid_until=self.end, paystack_customer_code="CUS_owner",
        )
        self.payment = StudyPayment.objects.create(
            user=self.user, tier="grow", plan="monthly", mode="test", status="succeeded",
            expected_amount_cents=3500, paystack_plan_code="PLN_original", verified_at=timezone.now(),
        )
        self.subscription = {
            "id": 11, "domain": "test", "subscription_code": "SUB_owner", "status": "active",
            # This embedded mode is omitted in real Paystack responses.
            "customer": {"customer_code": "CUS_owner", "email": "private@example.com"},
            "plan": {"domain": "test", "plan_code": "PLN_original"},
            "createdAt": timezone.now().isoformat(), "email_token": "privateCancellationToken",
        }
        self.fetch = patch.object(PaystackTestClient, "fetch_subscription", return_value=self.subscription).start()
        self.writes = patch.object(PaystackTestClient, "_request", side_effect=AssertionError("Unexpected provider request")).start()
        self.addCleanup(patch.stopall)
        self.receipt = self.make_receipt()

    def make_receipt(self, *, event="subscription.create", mode="test", snapshot=None):
        snapshot = snapshot if snapshot is not None else {
            "schema_version": 1, "domain": "test", "object_id": 11,
            "subscription_code": "SUB_owner", "customer_code": "CUS_owner", "plan_code": "PLN_original",
        }
        return PaystackWebhookReceipt.objects.create(
            mode=mode, event_type=event, snapshot=snapshot,
            payload_sha256=hashlib.sha256(str(PaystackWebhookReceipt.objects.count()).encode()).hexdigest(),
        )

    def process(self, receipt=None):
        return process_test_subscription_receipt((receipt or self.receipt).pk)

    def assert_member_unchanged(self):
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, "active")
        self.assertEqual(self.member.paid_until, self.end)
        self.assertIsNone(self.member.paystack_subscription_code)

    def test_create_links_only_after_verified_checkout_and_never_records_another_payment(self):
        before = list(StudyPayment.objects.values())
        result = self.process()
        self.member.refresh_from_db()
        self.assertEqual(result.processing_status, "processed")
        self.assertEqual(result.attempt_count, 1)
        self.assertIsNotNone(result.processed_at)
        self.assertEqual(self.member.paystack_subscription_code, "SUB_owner")
        self.assertEqual(self.member.status, "active")
        self.assertEqual(self.member.paid_until, self.end)
        self.assertEqual(list(StudyPayment.objects.values()), before)
        self.fetch.assert_called_once_with("SUB_owner")
        self.writes.assert_not_called()

    def test_reprocessing_completed_receipt_is_idempotent_without_network(self):
        self.process()
        first = PaystackWebhookReceipt.objects.get(pk=self.receipt.pk)
        result = self.process()
        self.assertEqual(result.processed_at, first.processed_at)
        self.assertEqual(result.attempt_count, 1)
        self.fetch.assert_called_once()

    def test_cancellation_keeps_paid_period_and_saved_material(self):
        from learning.models import Subject
        subject = Subject.objects.create(user=self.user, name="Biology")
        self.subscription["status"] = "non-renewing"
        result = self.process(self.make_receipt(event="subscription.not_renew"))
        self.member.refresh_from_db()
        self.assertEqual(result.processing_status, "processed")
        self.assertEqual(self.member.status, "non_renewing")
        self.assertEqual(self.member.paid_until, self.end)
        self.assertEqual(get_study_tier(self.user), StudyTier.GROW)
        self.assertTrue(Subject.objects.filter(pk=subject.pk).exists())
        self.writes.assert_not_called()

    def test_disable_after_paid_period_expires_access_without_deleting_data(self):
        end = timezone.now() - timedelta(days=1)
        StudyMembership.objects.filter(pk=self.member.pk).update(paid_until=end, grace_until=timezone.now() + timedelta(days=5))
        self.subscription["status"] = "cancelled"
        self.process(self.make_receipt(event="subscription.disable"))
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, "expired")
        self.assertEqual(self.member.paid_until, end)
        self.assertIsNone(self.member.grace_until)
        self.assertEqual(get_study_tier(self.user), StudyTier.FREE)
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_lifetime_beta_access_is_not_removed(self):
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        self.subscription["status"] = "complete"
        self.process()
        self.user.refresh_from_db()
        self.assertTrue(self.user.beta_lifetime_access)
        self.assertEqual(get_study_tier(self.user), StudyTier.BLOOM)

    def test_active_or_attention_metadata_never_reactivates_or_extends_access(self):
        for local_status in ("non_renewing", "past_due", "expired"):
            for provider_status in ("active", "attention"):
                StudyMembership.objects.filter(pk=self.member.pk).update(status=local_status)
                self.subscription["status"] = provider_status
                self.process(self.make_receipt())
                self.member.refresh_from_db()
                self.assertEqual(self.member.status, local_status)
                self.assertEqual(self.member.paid_until, self.end)

    def test_late_event_uses_current_provider_state_not_signed_old_status(self):
        receipt = self.make_receipt(event="subscription.disable")
        receipt.snapshot["provider_status"] = "cancelled"
        receipt.save(update_fields=["snapshot"])
        self.process(receipt)
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, "active")
        self.assertEqual(self.member.paid_until, self.end)

    def test_unverified_checkout_is_retried_not_guessed_from_customer_email(self):
        StudyPayment.objects.filter(pk=self.payment.pk).update(verified_at=None)
        result = self.process()
        self.assertEqual(result.processing_status, "retry")
        self.assertEqual(result.last_result, "checkout_not_verified")
        self.assertIsNone(result.processed_at)
        self.assertGreater(result.next_attempt_at, timezone.now())
        self.assert_member_unchanged()
        StudyPayment.objects.filter(pk=self.payment.pk).update(verified_at=timezone.now())
        PaystackWebhookReceipt.objects.filter(pk=result.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.process().processing_status, "processed")

    def test_provider_failure_retries_with_backoff_and_stores_no_exception_secrets(self):
        self.fetch.side_effect = PaystackError("sk_test_private privateCancellationToken")
        result = self.process()
        self.assertEqual(result.processing_status, "retry")
        self.assertEqual(result.last_result, "provider_unavailable")
        self.assertEqual(result.attempt_count, 1)
        again = self.process()
        self.assertEqual(again.attempt_count, 1)
        self.fetch.assert_called_once()
        stored = json.dumps(list(PaystackWebhookReceipt.objects.values()), default=str)
        self.assertNotIn("sk_test_private", stored)
        self.assertNotIn("privateCancellationToken", stored)
        self.assert_member_unchanged()

    def test_api_identifiers_must_match_notification_hints(self):
        for field, value in (("subscription_code", "SUB_other"), ("id", 22)):
            response = deepcopy(self.subscription)
            response[field] = value
            self.fetch.return_value = response
            result = self.process(self.make_receipt())
            self.assertEqual(result.processing_status, "ignored")
            self.assertEqual(result.last_result, "notification_mismatch")
            self.assert_member_unchanged()

    def test_live_or_foreign_provider_records_never_update_membership(self):
        for path, value in (
            (("domain",), "live"), (("plan", "domain"), "live"),
            (("customer", "domain"), "live"), (("customer", "customer_code"), "CUS_other"),
            (("plan", "plan_code"), "PLN_other"),
        ):
            response = deepcopy(self.subscription)
            target = response
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            self.fetch.return_value = response
            result = self.process(self.make_receipt())
            self.assertIn(result.processing_status, ("retry", "ignored"))
            self.assert_member_unchanged()

    def test_existing_live_membership_cannot_be_linked_or_changed(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(payment_mode="live", paystack_subscription_code="SUB_owner")
        before = list(StudyMembership.objects.values())
        result = self.process()
        self.assertEqual(result.processing_status, "ignored")
        self.assertEqual(list(StudyMembership.objects.values()), before)

    def test_existing_subscription_code_cannot_be_overwritten(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(paystack_subscription_code="SUB_current")
        result = self.process()
        self.assertEqual(result.processing_status, "ignored")
        self.member.refresh_from_db()
        self.assertEqual(self.member.paystack_subscription_code, "SUB_current")

    def test_shared_customer_with_two_verified_memberships_is_not_guessed(self):
        other = get_user_model().objects.create_user(username="ambiguous-student")
        StudyMembership.objects.create(user=other, tier="grow", plan="monthly", payment_mode="test", paystack_customer_code="CUS_owner")
        StudyPayment.objects.create(
            user=other, tier="grow", plan="monthly", mode="test", status="succeeded",
            expected_amount_cents=3500, paystack_plan_code="PLN_original", verified_at=timezone.now(),
        )
        result = self.process()
        self.assertEqual(result.processing_status, "retry")
        self.assertEqual(result.last_result, "ambiguous_membership")
        self.assert_member_unchanged()

    def test_old_unrelated_subscription_cannot_be_linked(self):
        self.subscription["createdAt"] = (self.payment.created_at - timedelta(days=20)).isoformat()
        result = self.process()
        self.assertEqual(result.processing_status, "retry")
        self.assertEqual(result.last_result, "subscription_time_mismatch")
        self.assert_member_unchanged()

    def test_boolean_schema_version_and_invalid_receipt_ids_are_not_accepted(self):
        receipt = self.make_receipt(snapshot={"schema_version": True, "domain": "test", "subscription_code": "SUB_owner"})
        self.assertEqual(self.process(receipt).processing_status, "ignored")
        for receipt_id in (True, 0, -1, "1", None):
            with self.subTest(receipt_id=receipt_id), self.assertRaises(ValueError):
                process_test_subscription_receipt(receipt_id)
        self.fetch.assert_not_called()

    def test_invalid_receipt_is_ignored_without_api_and_other_event_types_are_left_queued(self):
        receipt = self.make_receipt(snapshot={"schema_version": 1, "domain": "live", "subscription_code": "SUB_owner"})
        self.assertEqual(self.process(receipt).processing_status, "ignored")
        self.fetch.assert_not_called()
        for event, mode in (("charge.success", "test"), ("invoice.update", "test"), ("subscription.create", "live")):
            receipt = self.make_receipt(event=event, mode=mode)
            with self.assertRaises(ValueError):
                self.process(receipt)
            receipt.refresh_from_db()
            self.assertEqual(receipt.processing_status, "received")

    def test_debug_disabled_and_live_keys_fail_before_processing(self):
        for options in ({"DEBUG": False}, {"PAYSTACK_TEST_CHECKOUT_ENABLED": False}, {"PAYSTACK_TEST_SECRET_KEY": "sk_live_dummy"}):
            with self.settings(**options), self.assertRaises(PaystackError):
                self.process()
        self.fetch.assert_not_called()
        self.assert_member_unchanged()

    def test_subscription_can_be_fetched_by_numeric_id_if_code_was_not_in_event(self):
        self.receipt.snapshot.pop("subscription_code")
        self.receipt.save(update_fields=["snapshot"])
        self.process()
        self.fetch.assert_called_once_with("11")

    def test_signed_http_receipt_then_processor_updates_profile(self):
        payload = {"event": "subscription.not_renew", "data": deepcopy(self.subscription)}
        body = json.dumps(payload).encode()
        signature = hmac.new(SANDBOX["PAYSTACK_TEST_SECRET_KEY"].encode(), body, hashlib.sha512).hexdigest()
        client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        response = client.post(reverse("paystack_test_webhook"), data=body, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=signature)
        self.assertEqual(response.status_code, 200)
        received = PaystackWebhookReceipt.objects.exclude(pk=self.receipt.pk).get()
        self.subscription["status"] = "non-renewing"
        self.process(received)
        client.force_login(self.user)
        self.assertContains(client.get(reverse("my_plan")), "Future renewals are stopped")

    def test_local_batch_guard_and_limit_and_event_filter(self):
        invoice = self.make_receipt(event="invoice.update")
        output = io.StringIO()
        with patch(COMMAND_MODULE + "._require_disposable_preview"):
            call_command("process_paystack_test_subscriptions", stdout=output, limit=1)
            with self.assertRaises(CommandError):
                call_command("process_paystack_test_subscriptions", stdout=io.StringIO(), limit=101)
        self.assertIn("processed (subscription_linked)", output.getvalue())
        self.assertNotIn("private@example.com", output.getvalue())
        self.assertNotIn("privateCancellationToken", output.getvalue())
        invoice.refresh_from_db()
        self.assertEqual(invoice.processing_status, "received")
        with patch(COMMAND_MODULE + "._require_disposable_preview", side_effect=CommandError("wrong DB")):
            with self.assertRaises(CommandError):
                call_command("process_paystack_test_subscriptions", stdout=io.StringIO())

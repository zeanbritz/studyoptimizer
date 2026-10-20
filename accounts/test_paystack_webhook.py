"""Signed test notifications only; no real key or Paystack API is used."""

import hashlib
import hmac
import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment
from .test_paystack_checkout import SANDBOX
from .webhook_views import INBOX_EVENTS, MAX_WEBHOOK_BYTES, paystack_test_webhook


@override_settings(**SANDBOX)
class PaystackWebhookTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        self.url = reverse("paystack_test_webhook")
        self.payload = {
            "event": "charge.success",
            "data": {
                "id": 345, "domain": "test", "reference": "SG-" + "a" * 32,
                "amount": 3500, "currency": "ZAR", "status": "success",
                "paid_at": timezone.now().isoformat(),
                "customer": {"id": 9, "customer_code": "CUS_owner", "email": "private@example.com"},
                "plan": "PLN_growTest", "plan_object": {"domain": "test", "plan_code": "PLN_growTest"},
                "authorization": {"authorization_code": "AUTH_private", "last4": "9876", "signature": "SIG_private"},
                "email_token": "privateCancellationToken", "metadata": {"secret": "privateMetadata"},
            },
        }

    def signed_post(self, payload=None, *, raw=None, signature=None, key=None, **extra):
        raw = raw if raw is not None else json.dumps(payload if payload is not None else self.payload).encode()
        if signature is None:
            signature = hmac.new((key or SANDBOX["PAYSTACK_TEST_SECRET_KEY"]).encode(), raw, hashlib.sha512).hexdigest()
        return self.client.post(self.url, data=raw, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=signature, **extra)

    def test_valid_signature_records_sanitized_receipt_without_csrf_or_login(self):
        with patch("accounts.paystack_client.build_opener") as network:
            response = self.signed_post()
        network.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"received": True, "duplicate": False, "membership_updates": False})
        receipt = PaystackWebhookReceipt.objects.get()
        self.assertEqual(receipt.event_type, "charge.success")
        self.assertEqual(receipt.mode, "test")
        self.assertIsNone(receipt.processed_at)
        self.assertEqual(receipt.snapshot["transaction_reference"], self.payload["data"]["reference"])
        self.assertEqual(receipt.snapshot["transaction_id"], 345)
        self.assertEqual(receipt.snapshot["customer_code"], "CUS_owner")
        self.assertEqual(receipt.snapshot["plan_code"], "PLN_growTest")
        self.assertEqual(receipt.snapshot["amount_cents"], 3500)
        stored = json.dumps(list(PaystackWebhookReceipt.objects.values()), default=str)
        for private in ("private@example.com", "AUTH_private", "9876", "SIG_private", "privateCancellationToken", "privateMetadata"):
            self.assertNotIn(private, stored)

    def test_exact_redelivery_returns_success_without_another_receipt(self):
        self.signed_post()
        receipt = PaystackWebhookReceipt.objects.get()
        response = self.signed_post()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["duplicate"])
        self.assertEqual(PaystackWebhookReceipt.objects.count(), 1)
        self.assertEqual(PaystackWebhookReceipt.objects.get().received_at, receipt.received_at)

    def test_receipts_have_database_enforced_deduplication(self):
        self.signed_post()
        receipt = PaystackWebhookReceipt.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaystackWebhookReceipt.objects.create(
                mode="test", event_type=receipt.event_type, payload_sha256=receipt.payload_sha256,
            )

    def test_missing_malformed_or_wrong_key_signature_never_creates_a_receipt(self):
        for signature in ("", "wrong", "g" * 128, "a" * 129, "0" * 128):
            with self.subTest(signature=signature):
                self.assertEqual(self.signed_post(signature=signature).status_code, 403)
        self.assertEqual(self.signed_post(key="sk_test_anotherBusiness").status_code, 403)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_signature_covers_exact_raw_bytes_not_reserialized_json(self):
        raw = json.dumps(self.payload).encode()
        signature = hmac.new(SANDBOX["PAYSTACK_TEST_SECRET_KEY"].encode(), raw, hashlib.sha512).hexdigest()
        self.assertEqual(self.signed_post(raw=raw + b" ", signature=signature).status_code, 403)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())
        self.assertEqual(self.signed_post(raw=raw, signature=signature.upper()).status_code, 200)

    def test_unsigned_json_is_rejected_before_parsing(self):
        self.assertEqual(self.signed_post(raw=b"invalid-json", signature="0" * 128).status_code, 403)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_signed_malformed_json_and_envelopes_are_rejected(self):
        raw_values = (
            b"invalid-json", b"[]", b"null", b'{"event": "charge.success"}',
            b'{"event":"charge.success","data":[]}',
            b'{"event":{},"data":{"domain":"test"}}',
            b'{"event":"charge.success","data":{"domain":"test","id":NaN}}',
            b'{"event":"charge.success","data":{"domain":"live","domain":"test","id":1}}',
            b'\xff',
        )
        for raw in raw_values:
            with self.subTest(raw=raw):
                self.assertEqual(self.signed_post(raw=raw).status_code, 400)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_large_bodies_are_rejected(self):
        raw = b" " * (MAX_WEBHOOK_BYTES + 1)
        self.assertEqual(self.signed_post(raw=raw).status_code, 413)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_django_memory_limit_does_not_produce_a_debug_error(self):
        with self.settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1):
            self.assertEqual(self.signed_post().status_code, 413)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_body_stream_is_bounded_even_if_content_length_is_missing(self):
        request = RequestFactory().post(self.url, data=b"{}", content_type="application/json")
        request.META["CONTENT_LENGTH"] = ""
        request.META["HTTP_X_PAYSTACK_SIGNATURE"] = "0" * 128
        request.read = Mock(return_value=b"x" * (MAX_WEBHOOK_BYTES + 1))
        response = paystack_test_webhook(request)
        request.read.assert_called_once_with(MAX_WEBHOOK_BYTES + 1)
        self.assertEqual(response.status_code, 413)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_wrong_content_type_and_http_methods_are_rejected(self):
        self.assertEqual(self.client.post(self.url, data="{}", content_type="text/plain").status_code, 415)
        for method in (self.client.get, self.client.put, self.client.delete):
            self.assertEqual(method(self.url).status_code, 405)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_disabled_sandbox_debug_off_or_live_key_never_accepts_notifications(self):
        for options in (
            {"DEBUG": False}, {"PAYSTACK_TEST_CHECKOUT_ENABLED": False},
            {"PAYSTACK_TEST_SECRET_KEY": "sk_live_dummy"}, {"PAYSTACK_TEST_SECRET_KEY": ""},
        ):
            with self.subTest(options=options), self.settings(**options):
                self.assertEqual(self.signed_post().status_code, 404)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_live_or_missing_top_level_mode_is_rejected_even_with_valid_test_signature(self):
        for domain in ("live", None, "", False):
            payload = deepcopy(self.payload)
            payload["data"]["domain"] = domain
            with self.subTest(domain=domain):
                self.assertEqual(self.signed_post(payload).status_code, 400)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_explicit_live_embedded_objects_are_rejected(self):
        for field in ("customer", "plan", "plan_object", "subscription", "transaction"):
            payload = deepcopy(self.payload)
            payload["data"][field] = {"domain": "live"}
            with self.subTest(field=field):
                self.assertEqual(self.signed_post(payload).status_code, 400)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_unhandled_signed_test_events_are_acknowledged_without_storing_private_data(self):
        payload = deepcopy(self.payload)
        payload["event"] = "customeridentification.success"
        response = self.signed_post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ignored"])
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def post_supported_events(self):
        for index, event_type in enumerate(sorted(INBOX_EVENTS), start=1):
            payload = deepcopy(self.payload)
            payload["event"] = event_type
            payload["data"].update({"id": index, "subscription_code": "SUB_owned", "invoice_code": "INV_owned"})
            with self.subTest(event=event_type):
                self.assertEqual(self.signed_post(payload).status_code, 200)

    def test_all_expected_subscription_invoice_and_charge_events_are_captured(self):
        self.post_supported_events()
        self.assertEqual(PaystackWebhookReceipt.objects.count(), len(INBOX_EVENTS))
        self.assertFalse(PaystackWebhookReceipt.objects.filter(processed_at__isnull=False).exists())

    def test_conflicting_or_invalid_codes_and_missing_identifiers_are_rejected(self):
        for changes in (
            {"plan_code": "PLN_other"}, {"customer_code": "CUS_other"},
            {"reference": "private@example.com"}, {"subscription_code": "not-a-code"},
        ):
            payload = deepcopy(self.payload)
            payload["data"].update(changes)
            with self.subTest(changes=changes):
                self.assertEqual(self.signed_post(payload).status_code, 400)
        self.assertEqual(self.signed_post({"event": "charge.success", "data": {"domain": "test"}}).status_code, 400)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_failed_storage_returns_retryable_status_without_leaking_exception(self):
        with patch("accounts.webhook_views.PaystackWebhookReceipt.objects.get_or_create", side_effect=DatabaseError("private-db-secret")):
            response = self.signed_post()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"private-db-secret", response.content)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_capturing_notifications_never_changes_users_payments_or_memberships(self):
        user = get_user_model().objects.create_user(username="untouched-beta", beta_lifetime_access=True)
        StudyMembership.objects.create(
            user=user, tier="grow", plan="monthly", payment_mode="test",
            status="non_renewing", paid_until=timezone.now() + timedelta(days=25),
        )
        StudyPayment.objects.create(user=user, tier="grow", plan="monthly", mode="test", expected_amount_cents=3500)
        before = [list(model.objects.values()) for model in (get_user_model(), StudyMembership, StudyPayment)]
        self.post_supported_events()
        after = [list(model.objects.values()) for model in (get_user_model(), StudyMembership, StudyPayment)]
        self.assertEqual(before, after)

    def test_admin_inbox_is_read_only_and_reserved_for_superusers(self):
        model_admin = admin.site._registry[PaystackWebhookReceipt]
        request = RequestFactory().get("/admin/")
        for active, superuser, expected in ((True, True, True), (True, False, False), (False, True, False)):
            request.user = SimpleNamespace(is_active=active, is_superuser=superuser)
            self.assertEqual(model_admin.has_view_permission(request), expected)
            self.assertEqual(model_admin.has_module_permission(request), expected)
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
        self.signed_post()
        self.assertEqual("Waiting for processing", model_admin.processing_state(PaystackWebhookReceipt.objects.get()))

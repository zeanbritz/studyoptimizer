"""No public tunnel, network listener, real secret or provider call in these tests."""

import hashlib
import hmac
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management.base import CommandError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from . import webhook_relay as relay
from .management.commands.create_paystack_test_user import PREVIEW_DATABASE
from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment
from .test_paystack_checkout import SANDBOX


GUARD_MODULE = "accounts.management.commands.create_paystack_test_user"


class _MemoryHandler(relay.WebhookRelayHandler):
    def setup(self):
        self.connection = self.request
        self.rfile = io.BytesIO(self.request.raw)
        self.wfile = io.BytesIO()

    def finish(self):
        self.request.response = self.wfile.getvalue()


class RelayHTTPTests(SimpleTestCase):
    def request(self, method="POST", path=relay.PUBLIC_PATH, body=b'{ "event": "test" }', headers=None, raw=None):
        fields = {
            "Host": "public-test.trycloudflare.com", "Content-Type": "application/json",
            "Content-Length": str(len(body)), "x-paystack-signature": "a" * 128,
        }
        fields.update(headers or {})
        if raw is None:
            raw = (method + " " + path + " HTTP/1.1\r\n").encode()
            raw += b"".join((key + ": " + value + "\r\n").encode() for key, value in fields.items() if value is not None)
            raw += b"\r\n" + body
        request = SimpleNamespace(raw=raw)
        _MemoryHandler(request, ("127.0.0.1", 55555), SimpleNamespace())
        self.response = request.response
        return int(self.response.split(b" ")[1])

    def test_only_exact_webhook_path_is_allowed_not_website_or_internal_target(self):
        with patch.object(relay, "_preview_request") as upstream:
            for path in (
                "/", "/admin/", "/login/", "/dashboard/", relay.PREVIEW_PATH,
                relay.PUBLIC_PATH + "?secret=private", "/%70ayments/paystack/test/webhook/",
                "/payments/../payments/paystack/test/webhook/", "/" + relay.PUBLIC_PATH,
                "http://127.0.0.1:8000" + relay.PUBLIC_PATH,
            ):
                with self.subTest(path=path):
                    self.assertEqual(self.request(path=path), 404)
            upstream.assert_not_called()

    def test_all_non_post_methods_are_rejected_without_forwarding(self):
        with patch.object(relay, "_preview_request") as upstream:
            for method in ("GET", "HEAD", "PUT", "DELETE", "OPTIONS", "PATCH", "TRACE", "CONNECT"):
                self.assertEqual(self.request(method=method), 404)
            upstream.assert_not_called()

    def test_raw_bytes_and_signature_preserved_but_only_minimal_ack_returned(self):
        body = b'{ "data": {"domain":"test"}, "event": "charge.success" }\n'
        with patch.object(relay, "_preview_request", return_value=(200, {
            "received": True, "membership_updates": False, "email": "private@example.com",
        })) as upstream:
            self.assertEqual(self.request(body=body), 200)
        upstream.assert_called_once_with("POST", body, "a" * 128)
        self.assertTrue(self.response.endswith(b'{"received":true}'))
        self.assertNotIn(b"private@example.com", self.response)
        self.assertIn(b"Cache-Control: no-store", self.response)
        self.assertIn(b"Connection: close", self.response)
        self.assertNotIn(b"Python", self.response)

    def test_signature_and_content_type_required_before_forwarding(self):
        with patch.object(relay, "_preview_request") as upstream:
            for value in (None, "", "0" * 127, "z" * 128, "0" * 129):
                self.assertEqual(self.request(headers={"x-paystack-signature": value}), 403)
            self.assertEqual(self.request(headers={"Content-Type": "text/plain"}), 415)
            upstream.assert_not_called()

    def test_body_size_missing_length_and_truncated_body_are_rejected(self):
        with patch.object(relay, "_preview_request") as upstream:
            self.assertEqual(self.request(headers={"Content-Length": str(relay.MAX_BODY + 1)}), 413)
            for length in (None, "-1", "invalid", "9" * 11):
                self.assertEqual(self.request(headers={"Content-Length": length}), 411)
            self.assertEqual(self.request(body=b"{}", headers={"Content-Length": "10"}), 400)
            upstream.assert_not_called()

    def test_ambiguous_framing_and_encodings_are_rejected(self):
        with patch.object(relay, "_preview_request") as upstream:
            for field, value, status in (
                ("Transfer-Encoding", "chunked", 400), ("Content-Encoding", "gzip", 415),
                ("Expect", "100-continue", 417),
            ):
                self.assertEqual(self.request(headers={field: value}), status)
            for field in ("Content-Length", "Content-Type", "x-paystack-signature"):
                raw = ("POST " + relay.PUBLIC_PATH + " HTTP/1.1\r\n" + field + ": 1\r\n" + field + ": 2\r\n\r\n").encode()
                self.assertEqual(self.request(raw=raw), 400)
            upstream.assert_not_called()

    def test_unexpected_success_cannot_be_mistaken_for_recorded_webhook(self):
        for data in (None, [], {}, {"received": True}, {"received": 1, "membership_updates": False}):
            with patch.object(relay, "_preview_request", return_value=(200, data)):
                self.assertEqual(self.request(), 503)

    def test_rejection_statuses_do_not_echo_debug_payload_or_request(self):
        for status in (400, 403, 413, 415, 429, 503):
            with patch.object(relay, "_preview_request", return_value=(status, {"private": "sk_test_private"})):
                self.assertEqual(self.request(), status)
                self.assertNotIn(b"private", self.response)

    def test_parser_errors_are_generic_and_requests_are_not_logged(self):
        log = io.StringIO()
        with patch("sys.stderr", log), patch.object(relay, "_preview_request") as upstream:
            self.assertEqual(self.request(raw=b"POST\t" + relay.PUBLIC_PATH.encode() + b" HTTP/1.1\r\n\r\n"), 400)
            self.request(method="PRIVATE-REQUEST")
            upstream.assert_not_called()
        self.assertEqual(log.getvalue(), "")
        self.assertNotIn(b"PRIVATE-REQUEST", self.response)


class RelayBackendTests(SimpleTestCase):
    def setUp(self):
        self.connection_patch = patch.object(relay.http.client, "HTTPConnection")
        self.factory = self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.connection = self.factory.return_value
        self.response = self.connection.getresponse.return_value
        self.response.status = 200
        self.response.getheader.return_value = "application/json"
        self.response.read.return_value = b'{"disposable_paystack_preview":true,"relay_protocol":1}'

    def test_target_is_fixed_loopback_no_redirects_proxy_or_external_host(self):
        self.assertTrue(relay.preview_ready())
        self.factory.assert_called_once_with("127.0.0.1", 8000, timeout=relay.IO_TIMEOUT)
        self.connection.request.assert_called_once_with("GET", relay.PREVIEW_PATH, body=None, headers={"Accept": "application/json"})
        self.connection.close.assert_called_once()

    def test_forward_only_required_headers_and_raw_body(self):
        body, signature = b'{ "raw": true }', "b" * 128
        relay._preview_request("POST", body, signature)
        self.connection.request.assert_called_once_with("POST", relay.PREVIEW_PATH, body=body, headers={
            "Accept": "application/json", "Content-Type": "application/json", "Content-Length": str(len(body)),
            "x-paystack-signature": signature,
        })
        self.response.read.assert_called_once_with(relay.MAX_ACK + 1)

    def test_debug_errors_redirects_and_inactive_preview_are_hidden(self):
        self.response.read.return_value = b"SECRET private database exception"
        for status in (301, 302, 307, 404, 500, 502, 503):
            self.response.status = status
            self.assertEqual(relay._preview_request("POST", b"{}", "b" * 128), (503, None))
        self.assertEqual(self.factory.call_count, 7)

    def test_malformed_or_large_acknowledgement_is_not_forwarded(self):
        for raw in (b"x" * (relay.MAX_ACK + 1), b"invalid json", b"\xff"):
            self.response.read.return_value = raw
            self.assertEqual(relay._preview_request("GET"), (503, None))
        self.response.read.return_value = b"{}"
        self.response.getheader.return_value = "text/html"
        self.assertEqual(relay._preview_request("GET"), (503, None))

    def test_backend_connection_failure_is_sanitized_and_closed(self):
        self.connection.request.side_effect = OSError("private connection details")
        self.assertEqual(relay._preview_request("GET"), (503, None))
        self.connection.close.assert_called_once()

    def test_readiness_requires_exact_safe_contract_not_boolean_protocol(self):
        for data in ({}, {"disposable_paystack_preview": 1, "relay_protocol": 1}, {"disposable_paystack_preview": True, "relay_protocol": True}):
            self.response.read.return_value = json.dumps(data).encode()
            self.assertFalse(relay.preview_ready())

    def test_main_refuses_to_open_listener_without_disposable_preview(self):
        with patch.object(relay, "preview_ready", return_value=False), patch.object(relay, "WebhookRelayServer") as server, patch("sys.stdout", io.StringIO()):
            self.assertEqual(relay.main([]), 1)
        server.assert_not_called()

    def test_main_uses_bounded_lifetime_loopback_and_cancels_timer_on_stop(self):
        with patch.object(relay, "preview_ready", return_value=True), patch.object(relay, "WebhookRelayServer") as factory, patch.object(relay.threading, "Timer") as timer, patch("sys.stdout", io.StringIO()):
            server = factory.return_value
            self.assertEqual(relay.main(["--minutes", "5"]), 0)
            factory.assert_called_once_with(("127.0.0.1", 8765))
            timer.assert_called_once_with(300, server.shutdown)
            timer.return_value.start.assert_called_once()
            timer.return_value.cancel.assert_called_once()

    def test_lifetime_and_bind_address_cannot_be_widened(self):
        for minutes in ("0", "121", "-1"):
            with self.assertRaises(Exception):
                relay._minutes(minutes)
        with self.assertRaises(ValueError):
            relay.WebhookRelayServer(("0.0.0.0", 8765))

    def test_busy_relay_rejects_new_request_without_creating_another_thread(self):
        server = object.__new__(relay.WebhookRelayServer)
        server._slots = Mock()
        server._slots.acquire.return_value = False
        server.shutdown_request = Mock()
        request = Mock()
        server.process_request(request, ("127.0.0.1", 1))
        request.settimeout.assert_called_once_with(relay.IO_TIMEOUT)
        request.sendall.assert_called_once()
        server.shutdown_request.assert_called_once_with(request)
        server._slots.release.assert_not_called()


@override_settings(**SANDBOX)
class PreviewRelayViewTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        self.url = reverse("local_preview_webhook")
        self.database = {"ENGINE": "django.db.backends.sqlite3", "NAME": PREVIEW_DATABASE}
        self.body = json.dumps({"event": "charge.success", "data": {
            "domain": "test", "reference": "SG-" + "a" * 32, "id": 123,
        }}).encode()
        self.signature = hmac.new(SANDBOX["PAYSTACK_TEST_SECRET_KEY"].encode(), self.body, hashlib.sha512).hexdigest()

    def guard_database(self):
        # The guard sees synthetic config; ORM writes still use Django's isolated
        # test database, never the actual preview file or a hosted database.
        return patch(GUARD_MODULE + ".connections", {"default": SimpleNamespace(settings_dict=self.database)})

    def deliver(self, signature=None, body=None):
        return self.client.post(self.url, data=body or self.body, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=signature or self.signature)

    def test_real_non_preview_test_database_is_rejected(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.deliver().status_code, 404)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_exact_disposable_config_returns_no_paths_credentials_or_user_data(self):
        with self.guard_database():
            response = self.client.get(self.url)
        self.assertEqual(response.json(), {"disposable_paystack_preview": True, "relay_protocol": 1})
        self.assertIn("no-cache", response.headers["Cache-Control"])

    def test_original_local_and_postgres_databases_are_rejected_on_every_delivery(self):
        for engine, name in (
            ("django.db.backends.sqlite3", "/app/db.sqlite3"),
            ("django.db.backends.sqlite3", "/tmp/another.sqlite3"),
            ("django.db.backends.postgresql", PREVIEW_DATABASE),
        ):
            self.database.update(ENGINE=engine, NAME=name)
            with self.guard_database():
                self.assertEqual(self.client.get(self.url).status_code, 404)
                self.assertEqual(self.deliver().status_code, 404)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_debug_flag_and_live_keys_never_open_relay_target(self):
        for changes in ({"DEBUG": False}, {"PAYSTACK_TEST_CHECKOUT_ENABLED": False}, {"PAYSTACK_TEST_SECRET_KEY": "sk_live_dummy"}):
            with self.settings(**changes), self.guard_database():
                self.assertEqual(self.deliver().status_code, 404)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

    def test_public_hostname_cannot_call_local_target(self):
        with self.guard_database():
            self.assertEqual(self.client.get(self.url, HTTP_HOST="studigarden.com").status_code, 404)

    def test_valid_signed_delivery_records_once_without_payment_or_provider_calls(self):
        with self.guard_database(), patch("accounts.paystack_client.build_opener") as provider:
            self.assertEqual(self.deliver().status_code, 200)
            self.assertEqual(self.deliver().status_code, 200)
        provider.assert_not_called()
        self.assertEqual(PaystackWebhookReceipt.objects.count(), 1)
        self.assertEqual(PaystackWebhookReceipt.objects.get().processing_status, "received")
        self.assertFalse(StudyMembership.objects.exists())
        self.assertFalse(StudyPayment.objects.exists())

    def test_invalid_signature_or_live_payload_still_rejected_by_original_receiver(self):
        live = self.body.replace(b'"test"', b'"live"')
        signature = hmac.new(SANDBOX["PAYSTACK_TEST_SECRET_KEY"].encode(), live, hashlib.sha512).hexdigest()
        with self.guard_database():
            self.assertEqual(self.deliver(signature="b" * 128).status_code, 403)
            self.assertEqual(self.deliver(body=live, signature=signature).status_code, 400)
        self.assertFalse(PaystackWebhookReceipt.objects.exists())

import io
import json
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from .paystack_client import PAYSTACK_USER_AGENT


@override_settings(
    DEBUG=True, PAYSTACK_TEST_CHECKOUT_ENABLED=True,
    PAYSTACK_TEST_SECRET_KEY="sk_test_dummyDiagnosticsKey",
    PAYSTACK_TEST_PLAN_CODES={"grow": "PLN_grow", "bloom": "PLN_bloom"},
)
class PaystackDiagnosticTests(SimpleTestCase):
    def run_check(self, **options):
        output = io.StringIO()
        call_command("check_paystack_test", stdout=output, **options)
        return output.getvalue()

    @patch("accounts.management.commands.check_paystack_test.build_opener")
    def test_only_gets_plans_and_prints_allowlisted_fields(self, opener):
        response = Mock(status=200, headers={})
        response.read.return_value = json.dumps({"status": True, "data": {
            "domain": "test", "amount": 3500, "subscriptions": [{"email": "private@example.com"}],
        }}).encode()
        opener.return_value.open.return_value.__enter__.return_value = response
        output = self.run_check(tier="grow")
        self.assertIn("grow: HTTP 200", output)
        self.assertIn("amount: 3500", output)
        self.assertNotIn("private@example.com", output)
        self.assertNotIn("sk_test_dummyDiagnosticsKey", output)
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("User-agent"), PAYSTACK_USER_AGENT)
        self.assertEqual(request.full_url, "https://api.paystack.co/plan/PLN_grow")
        opener.return_value.open.assert_called_once()

    @patch("accounts.management.commands.check_paystack_test.build_opener")
    def test_error_reason_redacts_key_and_address(self, opener):
        body = {"status": False, "code": "ip_denied", "message": "IP 192.0.2.1 denied for sk_test_dummyDiagnosticsKey"}
        opener.return_value.open.side_effect = HTTPError(
            "https://api.paystack.co/plan/PLN_grow", 403, "Forbidden", {},
            io.BytesIO(json.dumps(body).encode()),
        )
        output = self.run_check(tier="grow")
        self.assertIn("grow: HTTP 403", output)
        self.assertIn("ip_denied", output)
        self.assertNotIn("sk_test_dummyDiagnosticsKey", output)
        self.assertNotIn("192.0.2.1", output)

    @patch("accounts.management.commands.check_paystack_test.build_opener")
    def test_gateway_classification_never_prints_html(self, opener):
        opener.return_value.open.side_effect = HTTPError(
            "https://api.paystack.co/plan/PLN_grow", 403, "Forbidden", {"Server": "cloudflare"},
            io.BytesIO(b"<html>error code: 1010; private challenge token</html>"),
        )
        output = self.run_check(tier="grow")
        self.assertIn("Gateway: Cloudflare", output)
        self.assertIn("Gateway error code: 1010", output)
        self.assertNotIn("private challenge", output)

    @patch("accounts.management.commands.check_paystack_test.build_opener")
    def test_connection_error_hides_exception_contents(self, opener):
        opener.return_value.open.side_effect = URLError("sk_test_dummyDiagnosticsKey")
        output = self.run_check(tier="grow")
        self.assertIn("connection error", output)
        self.assertNotIn("sk_test_dummyDiagnosticsKey", output)

    @patch("accounts.management.commands.check_paystack_test.build_opener")
    def test_live_key_is_rejected_before_request(self, opener):
        with self.settings(PAYSTACK_TEST_SECRET_KEY="sk_live_dummy"), self.assertRaises(CommandError):
            self.run_check()
        opener.assert_not_called()

    @patch("accounts.management.commands.check_paystack_test.build_opener")
    def test_default_checks_both_tiers_with_get_only(self, opener):
        response = Mock(status=200, headers={})
        response.read.return_value = b'{"status":true,"data":{"domain":"test"}}'
        opener.return_value.open.return_value.__enter__.return_value = response
        output = self.run_check()
        self.assertIn("grow: HTTP 200", output)
        self.assertIn("bloom: HTTP 200", output)
        self.assertEqual(opener.return_value.open.call_count, 2)
        for call in opener.return_value.open.call_args_list:
            self.assertEqual(call.args[0].get_method(), "GET")

    @patch("accounts.management.commands.check_paystack_test.build_opener")
    def test_nested_gateway_errors_are_redacted(self, opener):
        for body in (
            {"error": {"code": "blocked", "message": "Denied sk_test_dummyDiagnosticsKey"}},
            {"errors": [{"error_name": "blocked", "description": "Denied sk_test_dummyDiagnosticsKey"}]},
            {"error": "Denied sk_test_dummyDiagnosticsKey"},
        ):
            opener.return_value.open.side_effect = HTTPError(
                "https://api.paystack.co/plan/PLN_grow", 403, "Forbidden", {"Server": "cloudflare"},
                io.BytesIO(json.dumps(body).encode()),
            )
            with self.subTest(body=body):
                output = self.run_check(tier="grow")
                self.assertIn("Denied [redacted key]", output)
                self.assertNotIn("sk_test_dummyDiagnosticsKey", output)

    @patch("accounts.management.commands.check_paystack_test.build_opener")
    def test_unknown_error_data_stays_hidden_but_is_not_silent(self, opener):
        opener.return_value.open.side_effect = HTTPError(
            "https://api.paystack.co/plan/PLN_grow", 403, "Forbidden", {},
            io.BytesIO(b'{"private_data":"secret challenge"}'),
        )
        output = self.run_check(tier="grow")
        self.assertIn("No printable error detail", output)
        self.assertNotIn("secret challenge", output)

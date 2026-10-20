"""Read-only diagnostics: never print keys, headers or raw gateway HTML."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.paystack_client import PAYSTACK_USER_AGENT, _NoRedirects, test_checkout_enabled


def _safe_text(value):
    text = str(value)
    if settings.PAYSTACK_TEST_SECRET_KEY:
        text = text.replace(settings.PAYSTACK_TEST_SECRET_KEY, "[redacted key]")
    text = re.sub(r"[sp]k_(?:test|live)_[A-Za-z0-9_+/.=-]+", "[redacted key]", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP address]", text)
    return " ".join(text.split())[:400]


class Command(BaseCommand):
    help = "Read-only Paystack TEST plan check; no payments or account changes."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--tier", choices=["grow", "bloom"])

    def handle(self, *args, **options):
        if not test_checkout_enabled():
            raise CommandError("Enable the local sandbox with a test key first. Live keys are not accepted.")
        self.stdout.write("Read-only test-plan check. No payments or account changes will be made.")
        opener = build_opener(_NoRedirects())
        for tier in ([options["tier"]] if options.get("tier") else ["grow", "bloom"]):
            code = settings.PAYSTACK_TEST_PLAN_CODES.get(tier, "")
            if not re.fullmatch(r"PLN_[A-Za-z0-9]+", code):
                self.stdout.write(f"{tier}: test plan code is missing or invalid.")
                continue
            request = Request(
                "https://api.paystack.co/plan/" + quote(code, safe=""), method="GET",
                headers={
                    "Authorization": "Bearer " + settings.PAYSTACK_TEST_SECRET_KEY,
                    "Content-Type": "application/json", "Accept": "application/json",
                    "User-Agent": PAYSTACK_USER_AGENT,
                },
            )
            try:
                with opener.open(request, timeout=12) as response:
                    self.stdout.write(f"{tier}: HTTP {response.status}")
                    self._report(response.read(16_385), response.headers, success=True)
            except HTTPError as error:
                self.stdout.write(f"{tier}: HTTP {error.code}")
                try:
                    self._report(error.read(16_385), error.headers, success=False)
                finally:
                    error.close()
            except URLError as error:
                self.stdout.write(f"{tier}: connection error ({type(error.reason).__name__}).")
            except (OSError, ValueError, TypeError) as error:
                self.stdout.write(f"{tier}: request failed ({type(error).__name__}).")

    def _report(self, raw, headers, *, success):
        if headers and "cloudflare" in headers.get("Server", "").lower():
            self.stdout.write("  Gateway: Cloudflare")
        if len(raw) > 16_384:
            self.stdout.write("  Response omitted: exceeds diagnostic size limit.")
            return
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            text = raw.decode("utf-8", errors="replace").lower()
            code = re.search(r"error\s*code\s*:\s*(\d{3,5})\b", text)
            self.stdout.write(
                "  Gateway error code: " + code.group(1) if code
                else "  Non-JSON gateway response (body hidden)."
            )
            return
        if not isinstance(body, dict):
            self.stdout.write("  Unexpected response format (body hidden).")
            return
        if success and body.get("status") is True and isinstance(body.get("data"), dict):
            for field in ("domain", "plan_code", "amount", "currency", "interval"):
                value = body["data"].get(field)
                if value is None or isinstance(value, (str, int, bool)):
                    self.stdout.write(f"  {field}: {_safe_text(value)}")
        else:
            printed = False
            # Error envelopes differ between the API and its gateway. Only
            # known error fields are printable, never arbitrary response data.
            envelopes = [body]
            if isinstance(body.get("error"), dict):
                envelopes.append(body["error"])
            if isinstance(body.get("errors"), list):
                envelopes.extend(body["errors"][:3])
            for envelope in envelopes:
                if isinstance(envelope, (str, int)):
                    self.stdout.write("  error: " + _safe_text(envelope))
                    printed = True
                elif isinstance(envelope, dict):
                    for field in (
                        "code", "message", "error", "error_code", "error_name",
                        "error_description", "detail", "description",
                    ):
                        value = envelope.get(field)
                        if isinstance(value, (str, int)):
                            self.stdout.write(f"  {field}: {_safe_text(value)}")
                            printed = True
            if not printed:
                self.stdout.write("  No printable error detail in provider response (body hidden).")

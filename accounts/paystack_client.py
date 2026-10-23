"""Mode-isolated Paystack clients. Never log credentials or API bodies."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings


# Paystack recommends an explicit User-Agent for Cloudflare API blocks:
# https://support.paystack.com/en/articles/2124290
# Identify this application honestly; TLS and all payment checks stay unchanged.
PAYSTACK_USER_AGENT = "StudiGarden-Payments/1.0 (+https://studigarden.com)"


class PaystackError(ValueError):
    """A deliberately non-sensitive message suitable for the checkout screen."""


def test_checkout_enabled():
    return bool(
        settings.DEBUG
        and getattr(settings, "PAYSTACK_TEST_CHECKOUT_ENABLED", False)
        and re.fullmatch(r"sk_test_[A-Za-z0-9]+", settings.PAYSTACK_TEST_SECRET_KEY)
    )


def checkout_callback_url():
    base = settings.PAYSTACK_TEST_CALLBACK_BASE_URL
    try:
        parsed = urlsplit(base)
        valid = (
            parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1"}
            and parsed.username is None and parsed.password is None
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
            and (parsed.port is None or 1 <= parsed.port <= 65535)
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise PaystackError("The test callback must use your local preview address.")
    return base.rstrip("/") + "/payments/paystack/test/return/"


def valid_authorization_url(value):
    if not isinstance(value, str) or len(value) > 500 or any(c.isspace() for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https" and parsed.netloc == "checkout.paystack.com"
            and parsed.path.strip("/") and not parsed.query and not parsed.fragment
        )
    except ValueError:
        return False


def live_billing_enabled():
    return bool(
        not settings.DEBUG
        and getattr(settings, "PAYSTACK_LIVE_ENABLED", False)
        and re.fullmatch(r"sk_live_[A-Za-z0-9]+", getattr(settings, "PAYSTACK_LIVE_SECRET_KEY", ""))
        and getattr(settings, "PAYSTACK_LIVE_BASE_URL", "") == "https://studigarden.com"
    )


def live_checkout_enabled():
    codes = getattr(settings, "PAYSTACK_LIVE_PLAN_CODES", {})
    return bool(
        live_billing_enabled() and getattr(settings, "PAYSTACK_LIVE_CHECKOUT_ENABLED", False)
        and isinstance(codes, dict)
        and all(isinstance(codes.get(tier), str) and re.fullmatch(r"PLN_[A-Za-z0-9]{1,96}", codes[tier])
                for tier in ("grow", "bloom"))
        and codes["grow"] != codes["bloom"]
    )


def live_callback_url():
    if not live_billing_enabled():
        raise PaystackError("Live payments are not available right now.")
    return settings.PAYSTACK_LIVE_BASE_URL + "/payments/paystack/return/"


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an Authorization header to another URL.
        return None


class PaystackTestClient:
    mode = "test"

    def __init__(self):
        if not test_checkout_enabled():
            raise PaystackError("Local test checkout is not enabled.")
        self._key = settings.PAYSTACK_TEST_SECRET_KEY

    def _request(self, method, path, payload=None, *, expect_list=False, allow_empty_data=False):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            "https://api.paystack.co" + path, data=data, method=method,
            headers={
                "Authorization": "Bearer " + self._key,
                "Content-Type": "application/json", "Accept": "application/json",
                "User-Agent": PAYSTACK_USER_AGENT,
            },
        )
        try:
            with build_opener(_NoRedirects()).open(request, timeout=12) as response:
                raw = response.read(1_048_577)
                if response.status != 200 or len(raw) > 1_048_576:
                    raise ValueError
                body = json.loads(raw)
            if not isinstance(body, dict) or body.get("status") is not True:
                raise ValueError
            result = body.get("data")
            if allow_empty_data and result is None:
                return {}
            if not isinstance(result, list if expect_list else dict):
                raise ValueError
            return result
        except (HTTPError, URLError, OSError, ValueError, TypeError):
            raise PaystackError(
                "Paystack could not complete this request. Please check its status before trying again."
            ) from None

    def fetch_plan(self, code):
        return self._request("GET", "/plan/" + quote(code, safe=""))

    def initialize(self, payload):
        return self._request("POST", "/transaction/initialize", payload)

    def verify(self, reference):
        return self._request("GET", "/transaction/verify/" + quote(reference, safe=""))

    def fetch_customer(self, code):
        return self._request("GET", "/customer/" + quote(code, safe=""))

    def fetch_subscription(self, code):
        return self._request("GET", "/subscription/" + quote(code, safe=""))

    def list_customer_subscriptions(self, customer_id):
        if type(customer_id) is not int or customer_id <= 0:
            raise PaystackError("A valid Paystack customer is required.")
        return self._request(
            "GET", f"/subscription?customer={customer_id}&perPage=100&page=1", expect_list=True,
        )

    def disable_subscription(self, code, token):
        # Paystack acknowledges this operation with status=true and no data field.
        return self._request(
            "POST", "/subscription/disable", {"code": code, "token": token},
            allow_empty_data=True,
        )

    def enable_subscription(self, code, token):
        return self._request(
            "POST", "/subscription/enable", {"code": code, "token": token}, allow_empty_data=True,
        )

    def create_subscription(self, *, customer_code, plan_code, authorization_code, start_date):
        return self._request("POST", "/subscription", {
            "customer": customer_code, "plan": plan_code,
            "authorization": authorization_code, "start_date": start_date.isoformat(),
        })


class PaystackLiveClient(PaystackTestClient):
    mode = "live"

    def __init__(self):
        if not live_billing_enabled():
            raise PaystackError("Live payments are not available right now.")
        self._key = settings.PAYSTACK_LIVE_SECRET_KEY

    def list_refunds(self, transaction_id):
        if type(transaction_id) is not int or transaction_id <= 0:
            raise PaystackError("A verified transaction is required.")
        return self._request("GET", f"/refund?transaction={transaction_id}&perPage=100&page=1", expect_list=True)

    def fetch_refund(self, refund_id):
        if type(refund_id) is not int or refund_id <= 0:
            raise PaystackError("A valid refund identifier is required.")
        return self._request("GET", f"/refund/{refund_id}")

    def create_full_refund(self, transaction_id, amount_cents, note, *, customer_note="StudiGarden 7-day first-payment refund"):
        # Called only by the durable refund outbox after eligibility and renewal
        # cancellation are confirmed. Never automatically repeat this POST.
        return self._request("POST", "/refund", {
            "transaction": transaction_id, "amount": amount_cents, "currency": "ZAR",
            "merchant_note": note, "customer_note": customer_note,
        })

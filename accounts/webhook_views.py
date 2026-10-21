"""Capture authenticated notifications into separate TEST and LIVE inboxes.

https://paystack.com/docs/payments/webhooks/#verify-event-origin
No provider API calls, raw payload storage, or entitlement changes happen here.
"""

import hashlib
import hmac
import json
import re

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import DatabaseError, transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST

from .models import PaystackWebhookReceipt, StudyPayment
from .paystack_client import test_checkout_enabled, live_billing_enabled


MAX_WEBHOOK_BYTES = 256 * 1024
INBOX_EVENTS = frozenset({
    "charge.success", "subscription.create", "subscription.not_renew",
    "subscription.disable", "invoice.create", "invoice.payment_failed", "invoice.update",
})


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def _object(value):
    return value if isinstance(value, dict) else {}


def _positive_id(value):
    return value if type(value) is int and 0 < value <= 9_223_372_036_854_775_807 else None


def _code(prefix, *values):
    codes = set()
    for value in values:
        if value is None or value == "":
            continue
        if not isinstance(value, str) or len(value) > 100 or not re.fullmatch(prefix + r"[A-Za-z0-9]+", value):
            raise ValueError("Invalid provider identifier")
        codes.add(value)
    if len(codes) > 1:
        raise ValueError("Conflicting provider identifiers")
    return next(iter(codes), None)


def _snapshot(event_type, data, mode="test"):
    if data.get("domain") != mode:
        raise ValueError("Test-mode notifications only")
    # Embedded customer domain can be omitted by Paystack, but an explicit
    # live-mode object must never be accepted into this sandbox inbox.
    for name in ("customer", "plan", "plan_object", "subscription", "transaction"):
        if isinstance(data.get(name), dict) and data[name].get("domain") not in (None, mode):
            raise ValueError("Mixed payment modes")
    if event_type not in INBOX_EVENTS:
        return None

    result = {"schema_version": 1, "domain": mode}
    if object_id := _positive_id(data.get("id")):
        result["object_id"] = object_id
    for name, prefix in (("customer", "CUS_"), ("plan", "PLN_"), ("subscription", "SUB_"), ("invoice", "INV_")):
        related = data.get(name)
        code = _code(
            prefix, data.get(name + "_code"), _object(related).get(name + "_code"),
            related if isinstance(related, str) else None,
            _object(data.get("plan_object")).get("plan_code") if name == "plan" else None,
        )
        if code:
            result[name + "_code"] = code
        related_id = _positive_id(related) or _positive_id(_object(related).get("id"))
        if related_id:
            result[name + "_id"] = related_id

    charge = data if event_type == "charge.success" else _object(data.get("transaction"))
    if reference := charge.get("reference"):
        if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z0-9._=-]{1,100}", reference):
            raise ValueError("Invalid transaction reference")
        result["transaction_reference"] = reference
    if transaction_id := _positive_id(charge.get("id")):
        result["transaction_id"] = transaction_id
    amount = data.get("amount")
    if type(amount) is int and 0 <= amount <= 9_223_372_036_854_775_807:
        result["amount_cents"] = amount
    if isinstance(data.get("currency"), str) and re.fullmatch(r"[A-Z]{3}", data["currency"]):
        result["currency"] = data["currency"]
    if data.get("status") in ("success", "failed", "pending", "active", "attention", "non-renewing", "cancelled", "complete", "disabled"):
        result["provider_status"] = data["status"]
    if type(data.get("paid")) is bool:
        result["paid"] = data["paid"]
    for name in ("paid_at", "period_start", "period_end", "createdAt"):
        value = data.get(name)
        if isinstance(value, str) and len(value) <= 64:
            parsed = parse_datetime(value)
            if parsed and timezone.is_aware(parsed):
                result[name] = parsed.isoformat()

    required = (
        "transaction_reference" if event_type == "charge.success"
        else "subscription_code" if event_type.startswith("subscription.") else "invoice_code"
    )
    if required not in result and "object_id" not in result:
        raise ValueError("Missing notification identifier")
    return result


@csrf_exempt
@never_cache
@require_POST
@sensitive_variables("body", "signature", "expected_signature", "payload")
def paystack_test_webhook(request):
    if not test_checkout_enabled():
        return HttpResponse(status=404)
    return _receive_webhook(request, "test", settings.PAYSTACK_TEST_SECRET_KEY)


@csrf_exempt
@never_cache
@require_POST
def paystack_live_webhook(request):
    if (not live_billing_enabled() or not request.is_secure()
            or request.get_host().lower() != "studigarden.com"):
        return HttpResponse(status=404)
    return _receive_webhook(request, "live", settings.PAYSTACK_LIVE_SECRET_KEY)


@sensitive_variables("body", "signature", "expected_signature", "payload", "key")
def _receive_webhook(request, mode, key):
    if request.content_type != "application/json":
        return HttpResponse(status=415)
    try:
        declared_size = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        return HttpResponse(status=400)
    body_limit = MAX_WEBHOOK_BYTES
    if settings.DATA_UPLOAD_MAX_MEMORY_SIZE is not None:
        body_limit = min(body_limit, settings.DATA_UPLOAD_MAX_MEMORY_SIZE)
    if declared_size < 0 or declared_size > body_limit:
        return HttpResponse(status=413)
    signature = request.headers.get("x-paystack-signature", "")
    if not re.fullmatch(r"[a-fA-F0-9]{128}", signature):
        return HttpResponse(status=403)
    try:
        # Bound the actual stream too, even if Content-Length is absent or
        # incorrect. Do not allocate an unbounded request.body before checking.
        body = request.read(body_limit + 1)
    except RequestDataTooBig:
        return HttpResponse(status=413)
    except OSError:
        return HttpResponse(status=400)
    if len(body) > body_limit:
        return HttpResponse(status=413)
    expected_signature = hmac.new(
        key.encode("utf-8"), body, hashlib.sha512,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature.lower()):
        return HttpResponse(status=403)
    try:
        payload = json.loads(body.decode("utf-8"), object_pairs_hook=_strict_object, parse_constant=_reject_constant)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise ValueError
        event_type = payload.get("event")
        if not isinstance(event_type, str) or not 1 <= len(event_type) <= 64:
            raise ValueError
        snapshot = _snapshot(event_type, payload["data"], mode)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        return HttpResponse(status=400)
    if snapshot is None:
        return JsonResponse({"received": True, "ignored": True, "membership_updates": False})
    try:
        with transaction.atomic():
            _, created = PaystackWebhookReceipt.objects.get_or_create(
                mode=mode, payload_sha256=hashlib.sha256(body).hexdigest(),
                defaults={"event_type": event_type, "snapshot": snapshot},
            )
    except DatabaseError:
        # Do not acknowledge a notification that was not durably recorded.
        return HttpResponse(status=503)
    return JsonResponse({"received": True, "duplicate": not created, "membership_updates": False})

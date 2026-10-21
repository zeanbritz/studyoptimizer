"""Loopback relay target, available only in the disposable local TEST database."""

from django.core.management.base import CommandError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .management.commands.create_paystack_test_user import _require_disposable_preview
from .webhook_views import paystack_test_webhook


@csrf_exempt
@never_cache
@require_http_methods(["GET", "POST"])
def local_preview_webhook(request):
    if request.get_host().split(":", 1)[0].lower() not in {"localhost", "127.0.0.1"}:
        return HttpResponse(status=404)
    try:
        # Recheck on EVERY delivery, not only when the relay first starts. A
        # production/Postgres/original local database must never be targeted.
        _require_disposable_preview()
    except CommandError:
        return HttpResponse(status=404)
    if request.method == "GET":
        # No paths, key values, user data, or database connection strings.
        return JsonResponse({"disposable_paystack_preview": True, "relay_protocol": 1})
    # Use exactly the same raw-byte signature, TEST mode, and bounded inbox checks.
    # Receiving a message still does not process it or call the payment provider.
    return paystack_test_webhook(request)

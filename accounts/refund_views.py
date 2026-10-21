from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .live_checkout_views import _require_live
from .refund_service import RefundNotAllowed, refunds_enabled, request_first_payment_refund


@never_cache
@login_required
@require_POST
def request_live_refund(request):
    _require_live(request)
    if not refunds_enabled():
        raise Http404
    if request.POST.get("confirm_refund") != "yes":
        messages.error(request, "Please confirm that a refund stops renewals and ends the refunded paid access.")
        return redirect("my_plan")
    try:
        refund = request_first_payment_refund(request.user)
    except RefundNotAllowed as exc:
        messages.error(request, str(exc))
    else:
        messages.info(request, "Refund request recorded. Eligible first-payment requests are approved automatically. Check its progress below.")
    return redirect("my_plan")

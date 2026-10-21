"""Authenticated production checkout; HMAC notifications have their own route."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import StudyPayment
from .payment_service import CheckoutNotAllowed
from .paystack_client import PaystackError, live_billing_enabled, live_checkout_enabled
from .paystack_checkout import PaymentNotFound, initialize_live_checkout, verify_live_checkout
from .subscription_service import cancel_live_membership


def _require_live(request, *, new_checkout=False):
    if (not live_billing_enabled() or not request.is_secure()
            or request.get_host().lower() != "studigarden.com"
            or (new_checkout and not live_checkout_enabled())):
        raise Http404


@never_cache
@login_required
@require_POST
def start_live_checkout(request):
    _require_live(request, new_checkout=True)
    if request.POST.get("confirm_subscription") != "yes":
        messages.error(request, "Please confirm the monthly price and automatic renewal before continuing.")
        return redirect("my_plan")
    try:
        payment = initialize_live_checkout(user=request.user, tier=request.POST.get("tier"))
    except (CheckoutNotAllowed, PaystackError) as exc:
        messages.error(request, str(exc))
        return redirect("my_plan")
    response = redirect(payment.authorization_url)
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@login_required
@require_GET
def live_checkout_return(request):
    _require_live(request)
    try:
        payment = verify_live_checkout(user=request.user, reference=request.GET.get("reference", ""))
    except PaymentNotFound:
        raise Http404 from None
    except (CheckoutNotAllowed, PaystackError) as exc:
        messages.error(request, str(exc))
    else:
        if payment.status == StudyPayment.Status.SUCCEEDED:
            messages.success(request, "Payment verified. Your paid plan is ready.")
        elif payment.status in {StudyPayment.Status.FAILED, StudyPayment.Status.ABANDONED}:
            messages.warning(request, "Payment was not completed. Your access has not changed.")
        else:
            messages.info(request, "Your payment is awaiting confirmation. Check payment status again shortly.")
    response = redirect("my_plan")
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@login_required
@require_POST
def cancel_live_plan(request):
    _require_live(request)
    if request.POST.get("confirm_cancel") != "yes":
        messages.error(request, "Please confirm that you want to stop future renewals.")
        return redirect("my_plan")
    try:
        cancel_live_membership(user=request.user)
    except (CheckoutNotAllowed, PaystackError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Future renewals are stopped. Your already-paid access continues until its end date.")
    return redirect("my_plan")

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import StudyPayment
from .payment_service import CheckoutNotAllowed
from .paystack_client import PaystackError, test_checkout_enabled
from .paystack_checkout import PaymentNotFound, initialize_test_checkout, verify_test_checkout
from .subscription_service import cancel_test_membership as cancel_membership_service


def _require_local_sandbox(request):
    host = request.get_host().split(":", 1)[0].lower()
    if not test_checkout_enabled() or host not in {"localhost", "127.0.0.1"}:
        raise Http404


@never_cache
@login_required
@require_POST
def start_test_checkout(request):
    _require_local_sandbox(request)
    try:
        payment = initialize_test_checkout(user=request.user, tier=request.POST.get("tier"))
    except (CheckoutNotAllowed, PaystackError) as exc:
        messages.error(request, str(exc))
        return redirect("my_plan")
    response = redirect(payment.authorization_url)
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@login_required
@require_GET
def test_checkout_return(request):
    _require_local_sandbox(request)
    try:
        payment = verify_test_checkout(user=request.user, reference=request.GET.get("reference", ""))
    except PaymentNotFound:
        raise Http404 from None
    except (CheckoutNotAllowed, PaystackError) as exc:
        messages.error(request, str(exc))
    else:
        if payment.status == StudyPayment.Status.SUCCEEDED:
            messages.success(request, "Test payment verified. Your sandbox membership has been recorded. No real money was charged.")
        elif payment.status in {StudyPayment.Status.FAILED, StudyPayment.Status.ABANDONED}:
            messages.warning(request, "The test payment was not completed. Your access has not changed.")
        else:
            messages.info(request, "Paystack has not confirmed this test payment yet. Check again from your Profile.")
    response = redirect("my_plan")
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@login_required
@require_POST
def cancel_test_membership(request):
    _require_local_sandbox(request)
    if request.POST.get("confirm_cancel") != "yes":
        messages.error(request, "Please confirm that you want to stop future renewals.")
        return redirect("my_plan")
    try:
        cancel_membership_service(user=request.user)
    except (CheckoutNotAllowed, PaystackError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Future test renewals are stopped. You keep any already-paid access until its end date.")
    return redirect("my_plan")

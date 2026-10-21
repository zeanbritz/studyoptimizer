from django.conf import settings
from django.shortcuts import render

from accounts.entitlements import FREE_LEARNING_ITEM_LIMIT, FREE_SUBJECT_LIMIT
from accounts.plans import PAID_STUDY_PLANS
from accounts.paystack_checkout import checkout_page_context, live_checkout_page_context


def home(request):
    return render(request, "landing/home.html")


def pricing(request):
    return render(request, "landing/pricing.html", {
        **checkout_page_context(request),
        **live_checkout_page_context(request),
        "paid_plans": PAID_STUDY_PLANS,
        "free_subject_limit": FREE_SUBJECT_LIMIT,
        "free_learning_item_limit": FREE_LEARNING_ITEM_LIMIT,
    })


def privacy_policy(request):
    return render(request, "landing/legal/privacy.html")


def terms_of_use(request):
    return render(request, "landing/legal/terms.html")


def cookie_policy(request):
    return render(request, "landing/legal/cookies.html")


def billing_policy(request):
    return render(request, "landing/legal/billing.html", {
        **live_checkout_page_context(request),
        "paid_plans": PAID_STUDY_PLANS,
        "support_email": settings.STUDIGARDEN_SUPPORT_EMAIL,
    })


def contact(request):
    return render(request, "landing/contact/contact.html", {"support_email": settings.STUDIGARDEN_SUPPORT_EMAIL})

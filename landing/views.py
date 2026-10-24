from django.conf import settings
from django.shortcuts import render

from accounts.entitlements import FREE_LEARNING_ITEM_LIMIT, FREE_SUBJECT_LIMIT
from accounts.plans import PAID_STUDY_PLANS, plan_selection_context
from accounts.paystack_checkout import checkout_page_context, live_checkout_page_context


def _legal_context():
    return {
        "legal_name": settings.STUDIGARDEN_LEGAL_NAME,
        "registration_number": settings.STUDIGARDEN_REGISTRATION_NUMBER,
        "company_type": settings.STUDIGARDEN_COMPANY_TYPE,
        "registration_date": settings.STUDIGARDEN_REGISTRATION_DATE,
        "effective_date": settings.STUDIGARDEN_LEGAL_EFFECTIVE_DATE,
        "website_url": settings.STUDIGARDEN_WEBSITE_URL,
        "support_email": settings.STUDIGARDEN_SUPPORT_EMAIL,
    }


def home(request):
    return render(request, "landing/home.html")


def pricing(request):
    return render(request, "landing/pricing.html", {
        **checkout_page_context(request),
        **live_checkout_page_context(request),
        **plan_selection_context(request),
        "paid_plans": PAID_STUDY_PLANS,
        "free_subject_limit": FREE_SUBJECT_LIMIT,
        "free_learning_item_limit": FREE_LEARNING_ITEM_LIMIT,
    })


def privacy_policy(request):
    return render(request, "landing/legal/privacy.html", _legal_context())


def terms_of_use(request):
    return render(request, "landing/legal/terms.html", _legal_context())


def cookie_policy(request):
    return render(request, "landing/legal/cookies.html", _legal_context())


def billing_policy(request):
    from accounts.plan_changes import plan_changes_enabled
    from accounts.plan_controls import billing_here
    return render(request, "landing/legal/billing.html", {
        **_legal_context(),
        **live_checkout_page_context(request),
        "paid_plans": PAID_STUDY_PLANS,
        "plan_switching_enabled": billing_here(request) and plan_changes_enabled(),
    })


def contact(request):
    return render(request, "landing/contact/contact.html", _legal_context())

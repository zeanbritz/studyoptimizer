from django.shortcuts import render


def home(request):
    return render(request, "landing/home.html")


def pricing(request):
    return render(request, "landing/pricing.html")


def privacy_policy(request):
    return render(request, "landing/legal/privacy.html")


def terms_of_use(request):
    return render(request, "landing/legal/terms.html")


def cookie_policy(request):
    return render(request, "landing/legal/cookies.html")


def billing_policy(request):
    return render(request, "landing/legal/billing.html")


def contact(request):
    return render(request, "landing/contact/contact.html")

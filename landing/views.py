from django.shortcuts import render


def home(request):
    return render(request, "landing/home.html")


def pricing(request):
    return render(request, "landing/pricing.html")
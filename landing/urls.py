from django.urls import path
from . import views


urlpatterns = [
    path("", views.home, name="landing"),
    path("pricing/", views.pricing, name="pricing"),
    path("privacy/", views.privacy_policy, name="privacy_policy"),
    path("terms/", views.terms_of_use, name="terms_of_use"),
    path("cookies/", views.cookie_policy, name="cookie_policy"),
    path("billing/", views.billing_policy, name="billing_policy"),
    path("contact/", views.contact, name="contact"),
]

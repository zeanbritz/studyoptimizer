from django.contrib import admin
from django.urls import include, path

from accounts.views import BetaSignupView


urlpatterns = [
    path("", include("landing.urls")),

    path("admin/", admin.site.urls),

    path("", include("accounts.urls")),
    path("accounts/signup/", BetaSignupView.as_view()),
    path("accounts/", include("allauth.urls")),

    path("dashboard/", include("dashboard.urls")),
    path("learning/", include("learning.urls")),
    path("practice/", include("practice.urls")),
]
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("", include("landing.urls")),

    path("admin/", admin.site.urls),

    path("", include("accounts.urls")),
    path("accounts/", include("allauth.urls")),

    path("dashboard/", include("dashboard.urls")),
    path("learning/", include("learning.urls")),
    path("practice/", include("practice.urls")),
]
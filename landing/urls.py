from django.urls import path
from . import views


urlpatterns = [
    path("", views.home, name="landing"),
    path("pricing/", views.pricing, name="pricing"),
]
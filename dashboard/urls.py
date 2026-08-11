from django.urls import path

from . import views


urlpatterns = [
    path(
        "",
        views.dashboard,
        name="dashboard",
    ),

    path(
        "onboarding/",
        views.onboarding,
        name="onboarding"
    ),

    path(
        "onboarding/subjects/",
        views.onboarding_subjects,
        name="onboarding_subjects"
    ),
]
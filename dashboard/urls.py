from django.urls import path

from . import views


urlpatterns = [

    path(
        "",
        views.dashboard,
        name="dashboard"
    ),

    path(
        "onboarding/",
        views.onboarding,
        name="onboarding"
    ),

    path(
        "goals/",
        views.goals,
        name="goals"
    ),

    path(
        "goals/subject/<int:subject_index>/",
        views.subject_detail,
        name="subject_detail"
    ),

]
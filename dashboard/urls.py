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
        "review/",
        views.review,
        name="review"
    ),

    path(
        "subjects/<int:subject_index>/",
        views.subject_detail,
        name="subject_detail"
    ),

    path(
        "subjects/<int:subject_index>/definition/",
        views.definition,
        name="definition"
    ),

    path(
        "review/definitions/",
        views.review_definitions,
        name=
        "review_definitions"
    ),

    path(
        "progress/",
        views.progress,
        name="progress",
    ),

    path(
        "review/formulas/",
        views.review_formulas,
        name="review_formulas",
    ),

]
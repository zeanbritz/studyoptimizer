from django.urls import path

from . import views


urlpatterns = [
    path(
        "formula/<int:formula_id>/",
        views.practice_formula,
        name="practice_formula",
    ),
]
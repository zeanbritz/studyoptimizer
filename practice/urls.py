from django.urls import path

from . import views

urlpatterns = [

    path(
        "formula/<int:formula_id>/",
        views.practice_formula,
        name="practice_formula",
    ),

    path(
        "formula/<int:formula_id>/reconstruct/",
        views.formula_reconstruction,
        name="formula_reconstruction",
    ),

    path(
        "subjects/<int:subject_index>/definition/",
        views.definition,
        name="practice_definition",
    ),
]
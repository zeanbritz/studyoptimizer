from django.urls import path

from . import views
from .views import definitions


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
        definitions.definition,
        name="practice_definition",
    ),

    path(
        "subjects/<int:subject_index>/definition/<int:definition_index>/edit/",
        definitions.edit_definition,
        name="edit_definition",
    ),

]
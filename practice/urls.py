from django.urls import path

from . import views
from .views import definitions


urlpatterns = [

    # ========================================================
    # FORMULA
    # ========================================================

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


    # ========================================================
    # DEFINITION
    # ========================================================

    path(
        "definition/<int:definition_id>/",
        definitions.practice_definition,
        name="practice_definition_review",
    ),

    path(
        "steps/<int:step_list_id>/review/",
        views.practice_step_review,
        name="practice_step_review",
    ),

]
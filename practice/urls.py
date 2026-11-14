from django.urls import path

from learning.review_navigation import review_navigation

from . import views
from .views import definitions


urlpatterns = [

    # ========================================================
    # FORMULA
    # ========================================================

    path(
        "formula/<int:formula_id>/",
        review_navigation(views.practice_formula),
        name="practice_formula",
    ),

    path(
        "formula/<int:formula_id>/reconstruct/",
        review_navigation(views.formula_reconstruction),
        name="formula_reconstruction",
    ),


    # ========================================================
    # DEFINITION
    # ========================================================

    path(
        "definition/<int:definition_id>/",
        review_navigation(definitions.practice_definition),
        name="practice_definition_review",
    ),

    path(
        "definitions/random/<int:subject_id>/",
        review_navigation(definitions.practice_definition_match),
        name="practice_definition_match",
    ),

    path(
        "definitions/random/<int:subject_id>/terms/",
        review_navigation(definitions.practice_definition_term_match),
        name="practice_definition_term_match",
    ),

    path(
        "steps/<int:step_list_id>/review/",
        review_navigation(views.practice_step_review),
        name="practice_step_review",
    ),

    # ========================================================
    # COMPARISON
    # ========================================================

    path(
        "comparison/<int:comparison_id>/review/",
        review_navigation(views.practice_comparison_review),
        name="practice_comparison_review",
    ),

]

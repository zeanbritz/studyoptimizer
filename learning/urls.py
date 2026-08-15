from django.urls import path

from . import views


urlpatterns = [

    # ========================================================
    # FORMULA
    # ========================================================

    path(
        "subjects/<int:subject_id>/formula/create/",
        views.create_formula,
        name="create_formula",
    ),

    path(
        "formulas/<int:formula_id>/",
        views.formula_detail,
        name="formula_detail",
    ),

    path(
        "formulas/<int:formula_id>/edit/",
        views.edit_formula,
        name="edit_formula",
    ),

    path(
        "formulas/<int:formula_id>/review/",
        views.review_formula,
        name="review_formula",
    ),

    path(
        "subjects/<int:subject_index>/formulas/review/",
        views.formula_review_list,
        name="formula_review_list",
    ),


    # ========================================================
    # DEFINITION
    # ========================================================

    path(
        "subjects/<int:subject_id>/definition/create/",
        views.create_definition,
        name="create_definition",
    ),

    path(
        "subjects/<int:subject_index>/definitions/review/",
        views.definition_review_list,
        name="definition_review_list",
    ),

    path(
        "definitions/<int:definition_id>/review/",
        views.review_definition,
        name="review_definition",
    ),

    path(
        "reviews/reset-today/",
        views.reset_today_reviews,
        name="reset_today_reviews",
    ),

    path(
        "subjects/<int:subject_id>/definitions/",
        views.definition_list,
        name="definition_list",
    ),

]
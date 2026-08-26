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

    path(
        "subjects/<int:subject_id>/formulas/",
        views.formula_list,
        name="formula_list",
    ),

    path(
        "formulas/<int:formula_id>/delete/",
        views.delete_formula,
        name="delete_formula",
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

    path(
        "definitions/<int:definition_id>/edit/",
        views.edit_definition,
        name="edit_definition",
    ),

    path(
        "definitions/<int:definition_id>/delete/",
        views.delete_definition,
        name="delete_definition",
    ),

    path(
        "subjects/<int:subject_index>/book-summary/",
        views.book_summary,
        name="book_summary",
    ),

    path(
        "subjects/<int:subject_id>/list/create/",
        views.create_list,
        name="create_list",
    ),

    path(
        "subjects/<int:subject_index>/lists/review/",
        views.list_review_list,
        name="list_review_list",
    ),

]
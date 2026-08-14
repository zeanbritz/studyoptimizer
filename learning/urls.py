from django.urls import path

from . import views


urlpatterns = [

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
        "subjects/<int:subject_index>/definitions/review/",
        views.definition_review_list,
        name="definition_review_list",
    ),

    path(
        "definitions/<int:definition_id>/review/",
        views.review_definition,
        name="review_definition",
    ),

]
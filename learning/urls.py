from django.urls import path

from . import views


urlpatterns = [

    path(
        "subjects/<int:subject_id>/formula/create/",
        views.create_formula,
        name="create_formula",
    ),

    path(
        "formula/<int:formula_id>/",
        views.formula_detail,
        name="formula_detail",
    ),

    path(
        "formula/<int:formula_id>/edit/",
        views.edit_formula,
        name="edit_formula",
    ),

    path(
        "formula/<int:formula_id>/review/",
        views.review_formula,
        name="review_formula",
    ),

]
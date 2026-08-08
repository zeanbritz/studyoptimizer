from django.urls import path
from . import views


urlpatterns = [
    path(
        "topic/<int:topic_id>/formula/add/",
        views.create_formula,
        name="create_formula",
    ),
]
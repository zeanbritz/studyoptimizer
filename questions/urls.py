from django.urls import path

from . import views

app_name = "questions"

urlpatterns = [
    path("", views.setup, name="setup"),
    path("quiz/<uuid:token>/", views.quiz, name="quiz"),
    path("image/<int:question_id>/", views.question_image, name="image"),
    path("subject/<int:subject_id>/", views.manage, name="manage"),
    path("subject/<int:subject_id>/bulk-add/", views.bulk_add, name="bulk_add"),
    path("subject/<int:subject_id>/<int:question_id>/", views.manage, name="edit"),
    path("subject/<int:subject_id>/<int:question_id>/delete/", views.delete, name="delete"),
]

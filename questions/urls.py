from django.urls import path

from . import views

app_name = "questions"

urlpatterns = [
    path("", views.setup, name="setup"),
    path("quiz/<uuid:token>/", views.quiz, name="quiz"),
    path("subject/<int:subject_id>/", views.manage, name="manage"),
    path("subject/<int:subject_id>/<int:question_id>/", views.manage, name="edit"),
    path("subject/<int:subject_id>/<int:question_id>/delete/", views.delete, name="delete"),
]

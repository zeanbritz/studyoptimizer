from django.urls import path

from . import views

app_name = "exams"

urlpatterns = [
    path("", views.calendar_view, name="calendar"),
]

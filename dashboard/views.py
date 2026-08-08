from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from learning.models import Subject, Topic, Formula


@login_required
def dashboard(request):

    subjects = (
        Subject.objects
        .filter(user=request.user)
        .prefetch_related("topics")
    )

    formulas = (
        Formula.objects
        .filter(
            knowledge_unit__topic__subject__user=request.user
        )
        .select_related(
            "knowledge_unit",
            "knowledge_unit__topic",
        )
    )

    return render(
        request,
        "dashboard/dashboard.html",
        {
            "subjects": subjects,
            "formulas": formulas,
        }
    )
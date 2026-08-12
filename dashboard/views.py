from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

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


@login_required
def onboarding(request):

    if request.method == "POST":

        request.session["onboarding_profile"] = {
            "workspace_name": request.POST.get(
                "workspace_name",
                ""
            ),
            "target_grade": request.POST.get(
                "target_grade",
                ""
            ),
            "study_hours": request.POST.get(
                "study_hours",
                ""
            ),
            "subject_count": request.POST.get(
                "subject_count",
                ""
            ),
        }

        request.session["onboarding_complete"] = True

        return redirect("goals")

    return render(
        request,
        "dashboard/onboarding.html"
    )

@login_required
def goals(request):

    profile = request.session.get(
        "onboarding_profile",
        {}
    )

    return render(
        request,
        "dashboard/goals.html",
        {
            "profile": profile,
        }
    )

@login_required
def goals(request):

    profile = request.session.get(
        "onboarding_profile"
    )

    return render(
        request,
        "dashboard/goals.html",
        {
            "profile": profile,
        }
    )
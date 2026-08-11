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
        }

        request.session["onboarding_complete"] = True

        return redirect("dashboard")

    return render(
        request,
        "dashboard/onboarding.html"
    )

    profile = request.session.get(
        "onboarding_profile"
    )

    if not profile:
        return redirect("onboarding")

    subject_count = int(
        profile.get("subject_count", 1)
    )

    if request.method == "POST":

        subjects = []

        for i in range(subject_count):

            subjects.append({
                "name": request.POST.get(
                    f"subject_{i}",
                    ""
                ),
                "target_grade": request.POST.get(
                    f"target_grade_{i}",
                    ""
                ),
                "exam_date": request.POST.get(
                    f"exam_date_{i}",
                    ""
                ),
            })

        request.session["onboarding_subjects"] = subjects

        return redirect("dashboard")

    return render(
        request,
        "dashboard/onboarding_subjects.html",
        {
            "profile": profile,
            "subject_count": subject_count,
            "subject_range": range(subject_count),
        }
    )
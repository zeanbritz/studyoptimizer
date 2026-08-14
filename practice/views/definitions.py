from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect


@login_required
def definition(request, subject_index):

    profile = request.session.get(
        "onboarding_profile"
    )

    if not profile:
        return redirect("onboarding")

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    try:
        subject_index = int(subject_index)

    except (ValueError, TypeError):

        return redirect("goals")


    if subject_index < 0 or subject_index >= len(subjects):

        return redirect("goals")


    subject = subjects[subject_index]


    return render(
        request,
        "practice/definition.html",
        {
            "subject": subject,
            "subject_index": subject_index,
        }
    )
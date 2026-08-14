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

    # Make sure the subject has a definitions list.
    if "definitions" not in subject:

        subject["definitions"] = []

    if request.method == "POST":

        term = request.POST.get(
            "term",
            ""
        ).strip()

        meaning = request.POST.get(
            "meaning",
            ""
        ).strip()

        if term and meaning:

            subject["definitions"].append({
                "term": term,
                "meaning": meaning,
            })

            subjects[subject_index] = subject

            request.session["onboarding_subjects"] = subjects

            request.session.modified = True

        return redirect(
            "practice_definition",
            subject_index=subject_index
        )

    return render(
        request,
        "practice/definition.html",
        {
            "subject": subject,
            "subject_index": subject_index,
            "definitions": subject["definitions"],
        }
    )
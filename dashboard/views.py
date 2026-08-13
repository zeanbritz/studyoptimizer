from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect


@login_required
def dashboard(request):

    return render(
        request,
        "dashboard/dashboard.html"
    )


@login_required
def onboarding(request):

    if request.method == "POST":

        workspace_name = request.POST.get(
            "workspace_name",
            ""
        ).strip()

        target_grade = request.POST.get(
            "target_grade",
            ""
        )

        study_hours = request.POST.get(
            "study_hours",
            ""
        )

        subject_count = request.POST.get(
            "subject_count",
            "1"
        )

        try:
            subject_count = int(subject_count)
        except (ValueError, TypeError):
            subject_count = 1

        subject_count = max(
            1,
            min(subject_count, 20)
        )

        request.session["onboarding_profile"] = {
            "workspace_name": workspace_name,
            "target_grade": target_grade,
            "study_hours": study_hours,
            "subject_count": subject_count,
        }

        subjects = []

        for i in range(subject_count):

            subjects.append({
                "name": "",
                "target_grade": "",
                "exam_date": "",
                "definitions": [],
            })

        request.session["onboarding_subjects"] = subjects

        request.session.modified = True

        return redirect("goals")

    return render(
        request,
        "dashboard/onboarding.html"
    )


@login_required
def goals(request):

    profile = request.session.get(
        "onboarding_profile"
    )

    if not profile:
        return redirect("onboarding")

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    return render(
        request,
        "dashboard/goals.html",
        {
            "profile": profile,
            "subjects": subjects,
        }
    )


@login_required
def subject_detail(request, subject_index):

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

    # Make sure older subjects that were created before
    # definitions existed still have a definitions list.
    if "definitions" not in subject:
        subject["definitions"] = []

    if request.method == "POST":

        subject["name"] = request.POST.get(
            "name",
            ""
        ).strip()

        subject["target_grade"] = request.POST.get(
            "target_grade",
            ""
        )

        subject["exam_date"] = request.POST.get(
            "exam_date",
            ""
        )

        subjects[subject_index] = subject

        request.session["onboarding_subjects"] = subjects

        request.session.modified = True

        return redirect("goals")

    return render(
        request,
        "dashboard/subject_detail.html",
        {
            "subject": subject,
            "subject_index": subject_index,
        }
    )


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

    # Make sure the definitions list exists.
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
            "definition",
            subject_index=subject_index
        )

    return render(
        request,
        "dashboard/definition.html",
        {
            "subject": subject,
            "subject_index": subject_index,
            "definitions": subject["definitions"],
        }
    )
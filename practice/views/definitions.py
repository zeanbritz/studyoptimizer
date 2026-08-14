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

    # Get definitions belonging to this subject.
    definitions = subject.get(
        "definitions",
        []
    )

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

            definitions.append({
                "term": term,
                "meaning": meaning,
            })

            subjects[subject_index][
                "definitions"
            ] = definitions

            request.session[
                "onboarding_subjects"
            ] = subjects

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
            "definitions": definitions,
        }
    )


@login_required
def edit_definition(
    request,
    subject_index,
    definition_index
):

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
        definition_index = int(definition_index)
    except (ValueError, TypeError):
        return redirect("goals")

    if (
        subject_index < 0
        or subject_index >= len(subjects)
    ):
        return redirect("goals")

    subject = subjects[subject_index]

    definitions = subject.get(
        "definitions",
        []
    )

    if (
        definition_index < 0
        or definition_index >= len(definitions)
    ):
        return redirect(
            "practice_definition",
            subject_index=subject_index
        )

    definition_item = definitions[
        definition_index
    ]

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

            definitions[
                definition_index
            ] = {
                "term": term,
                "meaning": meaning,
            }

            subjects[
                subject_index
            ]["definitions"] = definitions

            request.session[
                "onboarding_subjects"
            ] = subjects

            request.session.modified = True

            return redirect(
                "practice_definition",
                subject_index=subject_index
            )

    return render(
        request,
        "practice/edit_definition.html",
        {
            "subject": subject,
            "subject_index": subject_index,
            "definition": definition_item,
            "definition_index": definition_index,
        }
    )
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
import json

from learning.models import Formula, StudentKnowledge


@login_required
def practice_formula(request, formula_id):

    formula = get_object_or_404(
        Formula,
        id=formula_id,
        knowledge_unit__topic__subject__user=request.user
    )

    knowledge_unit = formula.knowledge_unit

    progress, created = StudentKnowledge.objects.get_or_create(
        student=request.user,
        knowledge_unit=knowledge_unit,
    )

    try:
        formula_elements = json.loads(
            formula.structure
        )
    except (json.JSONDecodeError, TypeError):
        formula_elements = []

    if request.method == "POST":

        result = request.POST.get("result")

        progress.review_count += 1

        if result == "correct":

            progress.correct_count += 1

            if progress.mastery_level < 6:
                progress.mastery_level += 1

        elif result == "incorrect":

            progress.incorrect_count += 1

            if progress.mastery_level > 0:
                progress.mastery_level -= 1

        progress.save()

        return redirect(
            "practice_formula",
            formula_id=formula.id
        )

    return render(
        request,
        "practice/practice_formula.html",
        {
            "formula": formula,
            "formula_elements": formula_elements,
            "progress": progress,
        }
    )
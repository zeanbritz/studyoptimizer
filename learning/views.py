from django.contrib.auth.decorators import login_required
import json

from django.shortcuts import render, redirect, get_object_or_404

from .forms import FormulaForm

from .models import (
    Subject,
    Topic,
    KnowledgeUnit,
    Formula,
    FormulaVariable,
)


def extract_variables(elements):
    """
    Find variables anywhere inside the formula structure,
    including inside fractions.
    """

    variables = []

    for element in elements:

        if element.get("type") == "variable":

            variables.append(element)

        elif element.get("type") == "fraction":

            variables.extend(
                extract_variables(
                    element.get("numerator", [])
                )
            )

            variables.extend(
                extract_variables(
                    element.get("denominator", [])
                )
            )

    return variables


@login_required
def create_formula(request, topic_id):

    topic = get_object_or_404(
        Topic,
        id=topic_id,
        subject__user=request.user
    )

    if request.method == "POST":

        form = FormulaForm(request.POST)

        if form.is_valid():

            knowledge_unit = KnowledgeUnit.objects.create(
                topic=topic,
                title=form.cleaned_data["title"],
                knowledge_type=KnowledgeUnit.KnowledgeType.FORMULA,
                difficulty=form.cleaned_data["difficulty"],
                estimated_minutes=form.cleaned_data["estimated_minutes"],
            )

            structure = request.POST.get(
                "formula_structure",
                "[]"
            )

            try:
                structure_data = json.loads(structure)

            except (json.JSONDecodeError, TypeError):
                structure_data = []


            formula = Formula.objects.create(
                knowledge_unit=knowledge_unit,
                structure=structure,
                purpose=form.cleaned_data["purpose"],
                when_to_use=form.cleaned_data["when_to_use"],
            )


            # Create variables from the entire formula,
            # including variables inside fractions.
            seen_symbols = set()
            variable_order = 1

            for element in extract_variables(structure_data):

                symbol = element.get(
                    "value",
                    ""
                ).strip()

                meaning = element.get(
                    "meaning",
                    ""
                ).strip()


                if not symbol:
                    continue


                # Only create one database variable
                # for each unique symbol.
                if symbol in seen_symbols:
                    continue


                seen_symbols.add(symbol)


                FormulaVariable.objects.create(
                    formula=formula,
                    symbol=symbol,
                    meaning=meaning,
                    order=variable_order,
                )

                variable_order += 1


            return redirect(
                "formula_detail",
                formula_id=formula.id
            )


    else:

        form = FormulaForm()


    return render(
        request,
        "learning/create_formula.html",
        {
            "form": form,
            "topic": topic,
        }
    )


@login_required
def formula_detail(request, formula_id):

    formula = get_object_or_404(
        Formula,
        id=formula_id,
        knowledge_unit__topic__subject__user=request.user
    )


    variables = formula.variables.all().order_by(
        "order"
    )


    try:
        formula_elements = json.loads(
            formula.structure
        )

    except (json.JSONDecodeError, TypeError):
        formula_elements = []


    return render(
        request,
        "learning/formula_detail.html",
        {
            "formula": formula,
            "variables": variables,
            "formula_elements": formula_elements,
        }
    )


@login_required
def edit_formula(request, formula_id):

    formula = get_object_or_404(
        Formula,
        id=formula_id,
        knowledge_unit__topic__subject__user=request.user
    )


    knowledge_unit = formula.knowledge_unit


    if request.method == "POST":

        form = FormulaForm(request.POST)


        if form.is_valid():

            knowledge_unit.title = form.cleaned_data["title"]

            knowledge_unit.difficulty = (
                form.cleaned_data["difficulty"]
            )

            knowledge_unit.estimated_minutes = (
                form.cleaned_data["estimated_minutes"]
            )

            knowledge_unit.save()


            formula.structure = request.POST.get(
                "formula_structure",
                "[]"
            )

            formula.purpose = form.cleaned_data["purpose"]

            formula.when_to_use = (
                form.cleaned_data["when_to_use"]
            )

            formula.save()


            # Read the updated formula structure.
            try:

                structure_data = json.loads(
                    formula.structure
                )

            except (json.JSONDecodeError, TypeError):

                structure_data = []


            # Remove the old variable records.
            formula.variables.all().delete()


            # Rebuild variables from the entire formula,
            # including variables inside fractions.
            seen_symbols = set()
            variable_order = 1


            for element in extract_variables(
                structure_data
            ):

                symbol = element.get(
                    "value",
                    ""
                ).strip()

                meaning = element.get(
                    "meaning",
                    ""
                ).strip()


                if not symbol:
                    continue


                # Only store each unique symbol once.
                if symbol in seen_symbols:
                    continue


                seen_symbols.add(symbol)


                FormulaVariable.objects.create(
                    formula=formula,
                    symbol=symbol,
                    meaning=meaning,
                    order=variable_order,
                )


                variable_order += 1


            return redirect(
                "formula_detail",
                formula_id=formula.id
            )


    else:

        form = FormulaForm(
            initial={
                "title": knowledge_unit.title,
                "difficulty": knowledge_unit.difficulty,
                "estimated_minutes": (
                    knowledge_unit.estimated_minutes
                ),
                "purpose": formula.purpose,
                "when_to_use": formula.when_to_use,
            }
        )


    return render(
        request,
        "learning/edit_formula.html",
        {
            "form": form,
            "formula": formula,
        }
    )


from django.utils import timezone
from .models import StudentKnowledge


@login_required
def review_formula(request, formula_id):

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

        result = request.POST.get(
            "result"
        )

        progress.review_count += 1

        progress.last_reviewed = timezone.now()

        if result == "correct":

            progress.correct_count += 1

            if progress.mastery_level < 6:
                progress.mastery_level += 1

        else:

            progress.incorrect_count += 1

            if progress.mastery_level > 0:
                progress.mastery_level -= 1

        progress.next_review = timezone.now()

        progress.save()

        return redirect(
            "formula_detail",
            formula_id=formula.id
        )


    return render(
        request,
        "learning/review_formula.html",
        {
            "formula": formula,
            "formula_elements": formula_elements,
            "progress": progress,
        }
    )
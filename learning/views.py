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


            variable_order = 1

            for element in structure_data:

                if element.get("type") != "variable":
                    continue

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
            knowledge_unit.difficulty = form.cleaned_data["difficulty"]
            knowledge_unit.estimated_minutes = form.cleaned_data["estimated_minutes"]
            knowledge_unit.save()

            formula.structure = request.POST.get(
                "formula_structure",
                "[]"
            )

            formula.purpose = form.cleaned_data["purpose"]
            formula.when_to_use = form.cleaned_data["when_to_use"]
            formula.save()


            # Rebuild the variable list
            try:
                structure_data = json.loads(
                    formula.structure
                )
            except (json.JSONDecodeError, TypeError):
                structure_data = []


            # Remove old variables
            formula.variables.all().delete()


            # Add current variables
            seen_symbols = set()
            variable_order = 1

            for element in structure_data:

                if element.get("type") != "variable":
                    continue

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


                # Only store each symbol once
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
                "estimated_minutes": knowledge_unit.estimated_minutes,
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
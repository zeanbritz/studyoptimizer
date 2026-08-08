from django.contrib.auth.decorators import login_required
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

            formula = Formula.objects.create(
                knowledge_unit=knowledge_unit,
                expression=form.cleaned_data["expression"],
                purpose=form.cleaned_data["purpose"],
                when_to_use=form.cleaned_data["when_to_use"],
            )

            if form.cleaned_data["variable_1_symbol"]:
                FormulaVariable.objects.create(
                    formula=formula,
                    symbol=form.cleaned_data["variable_1_symbol"],
                    meaning=form.cleaned_data["variable_1_meaning"],
                    order=1,
                )


            if form.cleaned_data["variable_2_symbol"]:
                FormulaVariable.objects.create(
                    formula=formula,
                    symbol=form.cleaned_data["variable_2_symbol"],
                    meaning=form.cleaned_data["variable_2_meaning"],
                    order=2,
                )

            return redirect("dashboard")

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
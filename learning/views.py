from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from datetime import timedelta

import json

from .forms import FormulaForm

from .models import (
    Subject,
    KnowledgeUnit,
    Formula,
    FormulaVariable,
    Definition,
    StudentKnowledge,
)


# ============================================================
# EXTRACT VARIABLES
# ============================================================

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
                    element.get(
                        "numerator",
                        []
                    )
                )
            )

            variables.extend(
                extract_variables(
                    element.get(
                        "denominator",
                        []
                    )
                )
            )

    return variables


# ============================================================
# CREATE FORMULA
# ============================================================

@login_required
def create_formula(request, subject_id):

    subject = get_object_or_404(
        Subject,
        id=subject_id,
        user=request.user
    )

    if request.method == "POST":

        form = FormulaForm(
            request.POST
        )

        if form.is_valid():

            knowledge_unit = KnowledgeUnit.objects.create(

                subject=subject,

                title=form.cleaned_data[
                    "title"
                ],

                knowledge_type=(
                    KnowledgeUnit
                    .KnowledgeType
                    .FORMULA
                ),

                difficulty=(
                    form.cleaned_data[
                        "difficulty"
                    ]
                ),

                estimated_minutes=(
                    form.cleaned_data[
                        "estimated_minutes"
                    ]
                ),

            )

            structure = request.POST.get(
                "formula_structure",
                "[]"
            )

            try:

                structure_data = json.loads(
                    structure
                )

            except (
                json.JSONDecodeError,
                TypeError
            ):

                structure_data = []

            formula = Formula.objects.create(

                knowledge_unit=knowledge_unit,

                structure=structure,

                purpose=(
                    form.cleaned_data[
                        "purpose"
                    ]
                ),

                when_to_use=(
                    form.cleaned_data[
                        "when_to_use"
                    ]
                ),

            )

            # ------------------------------------------------
            # CREATE VARIABLES
            # ------------------------------------------------

            seen_symbols = set()

            variable_order = 1

            for element in extract_variables(
                structure_data
            ):

                symbol = str(
                    element.get(
                        "value",
                        ""
                    )
                ).strip()

                meaning = str(
                    element.get(
                        "meaning",
                        ""
                    )
                ).strip()

                if not symbol:
                    continue

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
            "subject": subject,
        }
    )


# ============================================================
# FORMULA DETAIL
# ============================================================

@login_required
def formula_detail(request, formula_id):

    formula = get_object_or_404(

        Formula,

        id=formula_id,

        knowledge_unit__subject__user=request.user

    )

    variables = (
        formula.variables
        .all()
        .order_by("order")
    )

    try:

        formula_elements = json.loads(
            formula.structure
        )

    except (
        json.JSONDecodeError,
        TypeError
    ):

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


# ============================================================
# EDIT FORMULA
# ============================================================

@login_required
def edit_formula(request, formula_id):

    formula = get_object_or_404(

        Formula,

        id=formula_id,

        knowledge_unit__subject__user=request.user

    )

    knowledge_unit = formula.knowledge_unit

    if request.method == "POST":

        form = FormulaForm(
            request.POST
        )

        if form.is_valid():

            knowledge_unit.title = (
                form.cleaned_data[
                    "title"
                ]
            )

            knowledge_unit.difficulty = (
                form.cleaned_data[
                    "difficulty"
                ]
            )

            knowledge_unit.estimated_minutes = (
                form.cleaned_data[
                    "estimated_minutes"
                ]
            )

            knowledge_unit.save()

            formula.structure = request.POST.get(
                "formula_structure",
                "[]"
            )

            formula.purpose = (
                form.cleaned_data[
                    "purpose"
                ]
            )

            formula.when_to_use = (
                form.cleaned_data[
                    "when_to_use"
                ]
            )

            formula.save()

            try:

                structure_data = json.loads(
                    formula.structure
                )

            except (
                json.JSONDecodeError,
                TypeError
            ):

                structure_data = []

            formula.variables.all().delete()

            seen_symbols = set()

            variable_order = 1

            for element in extract_variables(
                structure_data
            ):

                symbol = str(
                    element.get(
                        "value",
                        ""
                    )
                ).strip()

                meaning = str(
                    element.get(
                        "meaning",
                        ""
                    )
                ).strip()

                if not symbol:
                    continue

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

                "title":
                    knowledge_unit.title,

                "difficulty":
                    knowledge_unit.difficulty,

                "estimated_minutes":
                    knowledge_unit.estimated_minutes,

                "purpose":
                    formula.purpose,

                "when_to_use":
                    formula.when_to_use,

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


# ============================================================
# REVIEW INTERVAL
# ============================================================

def get_review_interval(mastery_level):

    intervals = {

        0: 0,

        1: 1,

        2: 2,

        3: 4,

        4: 7,

        5: 14,

        6: 30,

    }

    return intervals.get(
        mastery_level,
        0
    )


# ============================================================
# REVIEW FORMULA
# ============================================================

@login_required
def review_formula(request, formula_id):

    formula = get_object_or_404(

        Formula,

        id=formula_id,

        knowledge_unit__subject__user=request.user

    )

    knowledge_unit = formula.knowledge_unit

    progress, created = (
        StudentKnowledge.objects.get_or_create(

            student=request.user,

            knowledge_unit=knowledge_unit,

        )
    )

    try:

        formula_elements = json.loads(
            formula.structure
        )

    except (
        json.JSONDecodeError,
        TypeError
    ):

        formula_elements = []

    if request.method == "POST":

        result = request.POST.get(
            "result"
        )

        progress.review_count += 1

        progress.last_reviewed = (
            timezone.now()
        )

        if result == "correct":

            progress.correct_count += 1

            if progress.mastery_level < 6:

                progress.mastery_level += 1

        else:

            progress.incorrect_count += 1

            if progress.mastery_level > 0:

                progress.mastery_level -= 1

        interval = get_review_interval(
            progress.mastery_level
        )

        progress.next_review = (
            timezone.now()
            + timedelta(days=interval)
        )

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


# ============================================================
# FORMULA REVIEW LIST
# ============================================================

@login_required
def formula_review_list(
    request,
    subject_index
):

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    try:

        subject_index = int(
            subject_index
        )

    except (
        ValueError,
        TypeError
    ):

        return redirect("goals")

    if (
        subject_index < 0
        or subject_index >= len(subjects)
    ):

        return redirect("goals")

    subject_data = subjects[
        subject_index
    ]

    # --------------------------------------------------------
    # FIND DATABASE SUBJECT
    # --------------------------------------------------------

    database_subject = None

    database_subject_id = (
        subject_data.get(
            "database_id"
        )
    )

    if database_subject_id:

        database_subject = Subject.objects.filter(
            id=database_subject_id,
            user=request.user
        ).first()

    if not database_subject:

        subject_name = subject_data.get(
            "name",
            ""
        ).strip()

        if subject_name:

            database_subject = Subject.objects.filter(
                user=request.user,
                name=subject_name
            ).first()

    # --------------------------------------------------------
    # FIND DUE FORMULAS
    # --------------------------------------------------------

    due_formulas = []

    if database_subject:

        today = timezone.localdate()

        knowledge_units = (
            KnowledgeUnit.objects
            .filter(
                subject=database_subject,
                knowledge_type=(
                    KnowledgeUnit
                    .KnowledgeType
                    .FORMULA
                ),
                active=True,
            )
            .select_related(
                "formula"
            )
        )

        for knowledge_unit in knowledge_units:

            formula = getattr(
                knowledge_unit,
                "formula",
                None
            )

            if not formula:
                continue

            progress = (
                StudentKnowledge.objects
                .filter(
                    student=request.user,
                    knowledge_unit=knowledge_unit
                )
                .first()
            )

            # Never reviewed = due immediately.
            if progress is None:

                due_formulas.append(
                    formula
                )

                continue

            # Reviewed before, check next review.
            if (
                progress.next_review is not None
                and progress.next_review.date()
                <= today
            ):

                due_formulas.append(
                    formula
                )

    return render(
        request,
        "learning/formula_review_list.html",
        {
            "subject": subject_data,
            "subject_index": subject_index,
            "formulas": due_formulas,
        }
    )


# ============================================================
# DEFINITION REVIEW LIST
# ============================================================

@login_required
def definition_review_list(
    request,
    subject_index
):

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    try:

        subject_index = int(
            subject_index
        )

    except (
        ValueError,
        TypeError
    ):

        return redirect("goals")

    if (
        subject_index < 0
        or subject_index >= len(subjects)
    ):

        return redirect("goals")

    subject_data = subjects[
        subject_index
    ]

    # --------------------------------------------------------
    # FIND DATABASE SUBJECT
    # --------------------------------------------------------

    database_subject = None

    database_subject_id = (
        subject_data.get(
            "database_id"
        )
    )

    if database_subject_id:

        database_subject = Subject.objects.filter(
            id=database_subject_id,
            user=request.user
        ).first()

    if not database_subject:

        subject_name = subject_data.get(
            "name",
            ""
        ).strip()

        if subject_name:

            database_subject = Subject.objects.filter(
                user=request.user,
                name=subject_name
            ).first()

    # --------------------------------------------------------
    # FIND DUE DEFINITIONS
    # --------------------------------------------------------

    due_definitions = []

    if database_subject:

        today = timezone.localdate()

        knowledge_units = (
            KnowledgeUnit.objects
            .filter(
                subject=database_subject,
                knowledge_type=(
                    KnowledgeUnit
                    .KnowledgeType
                    .DEFINITION
                ),
                active=True,
            )
            .select_related(
                "definition"
            )
        )

        for knowledge_unit in knowledge_units:

            definition = getattr(
                knowledge_unit,
                "definition",
                None
            )

            if not definition:
                continue

            progress = (
                StudentKnowledge.objects
                .filter(
                    student=request.user,
                    knowledge_unit=knowledge_unit
                )
                .first()
            )

            # Never reviewed = due immediately.
            if progress is None:

                due_definitions.append(
                    definition
                )

                continue

            # Reviewed before and due again.
            if (
                progress.next_review is not None
                and progress.next_review.date()
                <= today
            ):

                due_definitions.append(
                    definition
                )

    return render(
        request,
        "learning/definition_review_list.html",
        {
            "subject": subject_data,
            "subject_index": subject_index,
            "definitions": due_definitions,
        }
    )


# ============================================================
# REVIEW DEFINITION
# ============================================================

@login_required
def review_definition(
    request,
    definition_id
):

    definition = get_object_or_404(

        Definition,

        id=definition_id,

        knowledge_unit__subject__user=request.user

    )

    knowledge_unit = (
        definition.knowledge_unit
    )

    progress, created = (
        StudentKnowledge.objects.get_or_create(

            student=request.user,

            knowledge_unit=knowledge_unit,

        )
    )

    # ========================================================
    # SUBMIT REVIEW
    # ========================================================

    if request.method == "POST":

        result = request.POST.get(
            "result"
        )

        progress.review_count += 1

        progress.last_reviewed = (
            timezone.now()
        )

        if result == "correct":

            progress.correct_count += 1

            if progress.mastery_level < 6:

                progress.mastery_level += 1

        else:

            progress.incorrect_count += 1

            if progress.mastery_level > 0:

                progress.mastery_level -= 1

        interval = get_review_interval(
            progress.mastery_level
        )

        progress.next_review = (
            timezone.now()
            + timedelta(days=interval)
        )

        progress.save()

        # ----------------------------------------------------
        # Return to the definition review list.
        # ----------------------------------------------------

        subject_id = (
            knowledge_unit.subject.id
        )

        subjects = request.session.get(
            "onboarding_subjects",
            []
        )

        subject_index = 0

        for index, subject in enumerate(
            subjects
        ):

            if subject.get(
                "database_id"
            ) == subject_id:

                subject_index = index

                break

        return redirect(
            "definition_review_list",
            subject_index=subject_index
        )

    # ========================================================
    # DISPLAY DEFINITION
    # ========================================================

    return render(
        request,
        "learning/review_definition.html",
        {
            "definition": definition,
            "progress": progress,
        }
    )
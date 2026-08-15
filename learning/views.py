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
def create_formula(
    request,
    subject_id
):

    # ========================================================
    # GET SUBJECT
    # ========================================================

    subject = get_object_or_404(
        Subject,
        id=subject_id,
        user=request.user
    )

    # ========================================================
    # FIND SUBJECT INDEX
    # ========================================================

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    subject_index = None

    # --------------------------------------------------------
    # FIRST: MATCH DATABASE ID
    # --------------------------------------------------------

    for index, subject_data in enumerate(
        subjects
    ):

        if (
            subject_data.get(
                "database_id"
            )
            == subject.id
        ):

            subject_index = index

            break

    # --------------------------------------------------------
    # FALLBACK: MATCH SUBJECT NAME
    # --------------------------------------------------------

    if subject_index is None:

        for index, subject_data in enumerate(
            subjects
        ):

            if (
                subject_data.get(
                    "name",
                    ""
                ).strip()
                == subject.name
            ):

                subject_index = index

                break

    # --------------------------------------------------------
    # FINAL FALLBACK
    # --------------------------------------------------------

    if subject_index is None:

        subject_index = 0

    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        form = FormulaForm(
            request.POST
        )

        if form.is_valid():

            # =================================================
            # CREATE KNOWLEDGE UNIT
            # =================================================

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

                active=True,

            )

            # =================================================
            # GET FORMULA STRUCTURE
            # =================================================

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

            # =================================================
            # CREATE FORMULA
            # =================================================

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

            # =================================================
            # CREATE FORMULA VARIABLES
            # =================================================

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

                seen_symbols.add(
                    symbol
                )

                FormulaVariable.objects.create(

                    formula=formula,

                    symbol=symbol,

                    meaning=meaning,

                    order=variable_order,

                )

                variable_order += 1

            # =================================================
            # FORMULA CREATED
            # =================================================

            return redirect(
                "formula_detail",
                formula_id=formula.id
            )

    else:

        form = FormulaForm()

    # ========================================================
    # DISPLAY CREATE PAGE
    # ========================================================

    return render(
        request,
        "learning/create_formula.html",
        {
            "form":
                form,

            "subject":
                subject,

            "subject_index":
                subject_index,
        }
    )


# ============================================================
# VIEW ALL FORMULAS
# ============================================================

@login_required
def formula_list(
    request,
    subject_id
):
    """
    Display every formula that belongs to
    the selected subject.
    """

    # --------------------------------------------------------
    # GET SUBJECT
    # --------------------------------------------------------

    subject = get_object_or_404(
        Subject,
        id=subject_id,
        user=request.user
    )

    # --------------------------------------------------------
    # SUBJECT INDEX
    # --------------------------------------------------------

    subject_index = request.GET.get(
        "subject_index",
        ""
    )

    try:

        subject_index = int(
            subject_index
        )

    except (
        ValueError,
        TypeError
    ):

        subject_index = 0

    # --------------------------------------------------------
    # GET ALL FORMULA KNOWLEDGE UNITS
    # --------------------------------------------------------

    knowledge_units = (
        KnowledgeUnit.objects
        .filter(
            subject=subject,

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
        .prefetch_related(
            "formula__variables"
        )
        .order_by(
            "title"
        )
    )

    # --------------------------------------------------------
    # GET ACTUAL FORMULAS
    # --------------------------------------------------------

    formulas = []

    for knowledge_unit in knowledge_units:

        formula = getattr(
            knowledge_unit,
            "formula",
            None
        )

        if not formula:
            continue

        # ----------------------------------------------------
        # PARSE FORMULA STRUCTURE
        # ----------------------------------------------------

        try:

            formula_elements = json.loads(
                formula.structure
            )

        except (
            json.JSONDecodeError,
            TypeError
        ):

            formula_elements = []

        # ----------------------------------------------------
        # ATTACH PARSED STRUCTURE TO FORMULA
        # ----------------------------------------------------

        formula.formula_elements = (
            formula_elements
        )

        formulas.append(
            formula
        )

    # --------------------------------------------------------
    # RENDER
    # --------------------------------------------------------

    return render(
        request,
        "learning/formula_list.html",
        {
            "subject": subject,

            "subject_index":
                subject_index,

            "formulas":
                formulas,
        }
    )


# ============================================================
# DELETE FORMULA
# ============================================================

@login_required
def delete_formula(request, formula_id):

    formula = get_object_or_404(
        Formula,
        id=formula_id,
        knowledge_unit__subject__user=request.user,
    )

    subject_id = formula.knowledge_unit.subject.id

    if request.method == "POST":

        formula.delete()

        return redirect(
            "formula_list",
            subject_id=subject_id
        )

    return redirect(
        "formula_list",
        subject_id=subject_id
    )



# ============================================================
# CREATE DEFINITION
# ============================================================

@login_required
def create_definition(
    request,
    subject_id
):

    # ========================================================
    # GET SUBJECT
    # ========================================================

    subject = get_object_or_404(
        Subject,
        id=subject_id,
        user=request.user
    )

    # ========================================================
    # SUBJECT INDEX
    # ========================================================

    subject_index = request.GET.get(
        "subject_index",
        request.POST.get(
            "subject_index",
            0
        )
    )

    try:

        subject_index = int(
            subject_index
        )

    except (
        ValueError,
        TypeError
    ):

        subject_index = 0

    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        term = request.POST.get(
            "term",
            ""
        ).strip()

        definition_text = request.POST.get(
            "definition",
            ""
        ).strip()

        # ====================================================
        # VALIDATION
        # ====================================================

        if term and definition_text:

            # =================================================
            # CREATE KNOWLEDGE UNIT
            # =================================================

            knowledge_unit = KnowledgeUnit.objects.create(

                subject=subject,

                title=term,

                knowledge_type=(
                    KnowledgeUnit
                    .KnowledgeType
                    .DEFINITION
                ),

                difficulty=1,

                estimated_minutes=2,

                active=True,

            )

            # =================================================
            # CREATE DEFINITION
            # =================================================

            Definition.objects.create(

                knowledge_unit=knowledge_unit,

                term=term,

                definition=definition_text,

            )

            # =================================================
            # NEW DEFINITIONS ARE IMMEDIATELY DUE
            # =================================================
            #
            # We deliberately do NOT create StudentKnowledge
            # here.
            #
            # When the review page sees that there is no
            # StudentKnowledge record, it treats the definition
            # as never reviewed and therefore due immediately.
            #
            # This is exactly how formulas work.
            # =================================================

        return redirect(
            "subject_detail",
            subject_index=subject_index
        )

    # ========================================================
    # DISPLAY CREATE PAGE
    # ========================================================

    return render(
        request,
        "learning/create_definition.html",
        {
            "subject": subject,
            "subject_index": subject_index,
        }
    )


# ============================================================
# FORMULA DETAIL
# ============================================================

@login_required
def formula_detail(
    request,
    formula_id
):

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

            "formula_elements":
                formula_elements,
        }
    )


# ============================================================
# EDIT FORMULA
# ============================================================

@login_required
def edit_formula(
    request,
    formula_id
):

    formula = get_object_or_404(

        Formula,

        id=formula_id,

        knowledge_unit__subject__user=request.user

    )

    knowledge_unit = (
        formula.knowledge_unit
    )

    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        form = FormulaForm(
            request.POST
        )

        if form.is_valid():

            # ================================================
            # UPDATE KNOWLEDGE UNIT
            # ================================================

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

            # ================================================
            # UPDATE FORMULA
            # ================================================

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

            # ================================================
            # READ STRUCTURE
            # ================================================

            try:

                structure_data = json.loads(
                    formula.structure
                )

            except (
                json.JSONDecodeError,
                TypeError
            ):

                structure_data = []

            # ================================================
            # DELETE OLD VARIABLES
            # ================================================

            formula.variables.all().delete()

            # ================================================
            # REBUILD VARIABLES
            # ================================================

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

                seen_symbols.add(
                    symbol
                )

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

    # ========================================================
    # GET
    # ========================================================

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

def get_review_interval(
    mastery_level
):

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

    # --------------------------------------------------------
    # The Practice app handles the actual formula review.
    # --------------------------------------------------------

    return redirect(
        "practice_formula",
        formula_id=formula.id
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

        return redirect(
            "goals"
        )

    if (
        subject_index < 0
        or subject_index >= len(subjects)
    ):

        return redirect(
            "goals"
        )

    subject_data = subjects[
        subject_index
    ]

    # ========================================================
    # FIND DATABASE SUBJECT
    # ========================================================

    database_subject = None

    database_subject_id = (
        subject_data.get(
            "database_id"
        )
    )

    if database_subject_id:

        database_subject = (
            Subject.objects.filter(
                id=database_subject_id,
                user=request.user
            ).first()
        )

    if not database_subject:

        subject_name = subject_data.get(
            "name",
            ""
        ).strip()

        if subject_name:

            database_subject = (
                Subject.objects.filter(
                    user=request.user,
                    name=subject_name
                ).first()
            )

    # ========================================================
    # FIND DUE FORMULAS
    # ========================================================

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

                    knowledge_unit=(
                        knowledge_unit
                    )
                )
                .first()
            )

            # ------------------------------------------------
            # NEVER REVIEWED
            # ------------------------------------------------

            if progress is None:

                due_formulas.append(
                    formula
                )

                continue

            # ------------------------------------------------
            # REVIEW DUE
            # ------------------------------------------------

            if (
                progress.next_review is not None
                and
                progress.next_review.date()
                <= today
            ):

                due_formulas.append(
                    formula
                )

    return render(
        request,
        "learning/formula_review_list.html",
        {
            "subject":
                subject_data,

            "subject_index":
                subject_index,

            "formulas":
                due_formulas,
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

        return redirect(
            "goals"
        )

    if (
        subject_index < 0
        or subject_index >= len(subjects)
    ):

        return redirect(
            "goals"
        )

    subject_data = subjects[
        subject_index
    ]

    # ========================================================
    # FIND DATABASE SUBJECT
    # ========================================================

    database_subject = None

    database_subject_id = (
        subject_data.get(
            "database_id"
        )
    )

    if database_subject_id:

        database_subject = (
            Subject.objects.filter(
                id=database_subject_id,
                user=request.user
            ).first()
        )

    if not database_subject:

        subject_name = subject_data.get(
            "name",
            ""
        ).strip()

        if subject_name:

            database_subject = (
                Subject.objects.filter(
                    user=request.user,
                    name=subject_name
                ).first()
            )

    # ========================================================
    # FIND DUE DEFINITIONS
    # ========================================================

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

                    knowledge_unit=(
                        knowledge_unit
                    )
                )
                .first()
            )

            # ------------------------------------------------
            # NEVER REVIEWED
            # ------------------------------------------------

            if progress is None:

                due_definitions.append(
                    definition
                )

                continue

            # ------------------------------------------------
            # REVIEW DUE
            # ------------------------------------------------

            if (
                progress.next_review is not None
                and
                progress.next_review.date()
                <= today
            ):

                due_definitions.append(
                    definition
                )

    return render(
        request,
        "learning/definition_review_list.html",
        {
            "subject":
                subject_data,

            "subject_index":
                subject_index,

            "definitions":
                due_definitions,
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
    # CREATE THE MISSING PART
    # ========================================================

    definition_text = definition.definition.strip()

    words = definition_text.split()

    if len(words) < 4:

        missing_text = definition_text

        before_text = ""

        after_text = ""

    else:

        missing_index = len(words) // 2

        missing_text = words[
            missing_index
        ]

        before_text = " ".join(
            words[:missing_index]
        )

        after_text = " ".join(
            words[missing_index + 1:]
        )

    # ========================================================
    # REVIEW SUBMISSION
    # ========================================================

    if request.method == "POST":

        answer = request.POST.get(
            "answer",
            ""
        ).strip()

        # ----------------------------------------------------
        # CHECK ANSWER
        # ----------------------------------------------------

        is_correct = (
            answer.casefold()
            == missing_text.casefold()
        )

        progress.review_count += 1

        progress.last_reviewed = (
            timezone.now()
        )

        # ====================================================
        # CORRECT
        # ====================================================

        if is_correct:

            progress.correct_count += 1

            if progress.mastery_level < 6:

                progress.mastery_level += 1

        # ====================================================
        # INCORRECT
        # ====================================================

        else:

            progress.incorrect_count += 1

            if progress.mastery_level > 0:

                progress.mastery_level -= 1

        # ====================================================
        # CALCULATE NEXT REVIEW
        # ====================================================

        interval = get_review_interval(
            progress.mastery_level
        )

        progress.next_review = (
            timezone.now()
            + timedelta(
                days=interval
            )
        )

        progress.save()

        # ====================================================
        # FIND SUBJECT
        # ====================================================

        subject = knowledge_unit.subject

        subject_id = subject.id

        # ====================================================
        # FIND NEXT DUE DEFINITION
        # ====================================================

        now = timezone.now()

        due_definitions = (
            Definition.objects
            .filter(
                knowledge_unit__subject=subject,

                knowledge_unit__knowledge_type=(
                    KnowledgeUnit
                    .KnowledgeType
                    .DEFINITION
                ),

                knowledge_unit__active=True,
            )
            .exclude(
                id=definition.id
            )
            .order_by(
                "id"
            )
        )

        next_definition = None

        for next_item in due_definitions:

            next_progress = (
                StudentKnowledge.objects
                .filter(
                    student=request.user,

                    knowledge_unit=(
                        next_item.knowledge_unit
                    )
                )
                .first()
            )

            # ------------------------------------------------
            # Never reviewed = due
            # ------------------------------------------------

            if next_progress is None:

                next_definition = next_item

                break

            # ------------------------------------------------
            # Already reviewed but due again
            # ------------------------------------------------

            if (
                next_progress.next_review
                is not None
                and
                next_progress.next_review
                <= now
            ):

                next_definition = next_item

                break

        # ====================================================
        # FIND SUBJECT INDEX
        # ====================================================

        subjects = request.session.get(
            "onboarding_subjects",
            []
        )

        subject_index = None

        for index, subject_data in enumerate(
            subjects
        ):

            if (
                subject_data.get(
                    "database_id"
                )
                == subject_id
            ):

                subject_index = index

                break

        # ----------------------------------------------------
        # FALLBACK: MATCH SUBJECT NAME
        # ----------------------------------------------------

        if subject_index is None:

            for index, subject_data in enumerate(
                subjects
            ):

                if (
                    subject_data.get(
                        "name",
                        ""
                    ).strip()
                    == subject.name
                ):

                    subject_index = index

                    break

        # ----------------------------------------------------
        # FINAL FALLBACK
        # ----------------------------------------------------

        if subject_index is None:

            subject_index = 0

        # ====================================================
        # SHOW RESULT
        # ====================================================

        return render(
            request,
            "learning/review_definition.html",
            {
                "definition":
                    definition,

                "progress":
                    progress,

                "before_text":
                    before_text,

                "missing_text":
                    missing_text,

                "after_text":
                    after_text,

                "answer":
                    answer,

                "is_correct":
                    is_correct,

                "submitted":
                    True,

                "subject_index":
                    subject_index,

                "next_definition":
                    next_definition,
            }
        )

    # ========================================================
    # DISPLAY REVIEW
    # ========================================================

    return render(
        request,
        "learning/review_definition.html",
        {
            "definition":
                definition,

            "progress":
                progress,

            "before_text":
                before_text,

            "missing_text":
                missing_text,

            "after_text":
                after_text,

            "submitted":
                False,
        }
    )


# ============================================================
# RESET TODAY'S REVIEWS
# ============================================================

@login_required
def reset_today_reviews(request):

    if request.method == "POST":

        StudentKnowledge.objects.filter(
            student=request.user
        ).update(
            next_review=timezone.now()
        )

    return redirect("dashboard")



# ============================================================
# VIEW ALL DEFINITIONS
# ============================================================

# ============================================================
# VIEW ALL DEFINITIONS
# ============================================================

@login_required
def definition_list(
    request,
    subject_id
):
    """
    Display every definition that belongs to
    the selected subject.

    The search only looks at the definition
    term/title. It does NOT search the
    definition description.
    """

    # --------------------------------------------------------
    # GET SUBJECT
    # --------------------------------------------------------

    subject = get_object_or_404(
        Subject,
        id=subject_id,
        user=request.user
    )

    # --------------------------------------------------------
    # FIND SUBJECT INDEX
    # --------------------------------------------------------

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    subject_index = None

    # --------------------------------------------------------
    # FIRST: MATCH DATABASE ID
    # --------------------------------------------------------

    for index, subject_data in enumerate(
        subjects
    ):

        if (
            subject_data.get(
                "database_id"
            )
            == subject.id
        ):

            subject_index = index

            break

    # --------------------------------------------------------
    # FALLBACK: MATCH SUBJECT NAME
    # --------------------------------------------------------

    if subject_index is None:

        for index, subject_data in enumerate(
            subjects
        ):

            if (
                subject_data.get(
                    "name",
                    ""
                ).strip()
                == subject.name
            ):

                subject_index = index

                break

    # --------------------------------------------------------
    # FINAL FALLBACK
    # --------------------------------------------------------

    if subject_index is None:

        subject_index = 0

    # --------------------------------------------------------
    # SEARCH
    # --------------------------------------------------------

    search_query = request.GET.get(
        "q",
        ""
    ).strip()

    # --------------------------------------------------------
    # GET ALL DEFINITION KNOWLEDGE UNITS
    # --------------------------------------------------------

    knowledge_units = (
        KnowledgeUnit.objects
        .filter(
            subject=subject,

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
        .order_by(
            "title"
        )
    )

    # --------------------------------------------------------
    # SEARCH ONLY TITLE / TERM
    # --------------------------------------------------------

    if search_query:

        knowledge_units = knowledge_units.filter(
            title__icontains=search_query
        )

    # --------------------------------------------------------
    # GET ACTUAL DEFINITIONS
    # --------------------------------------------------------

    definitions = []

    for knowledge_unit in knowledge_units:

        definition = getattr(
            knowledge_unit,
            "definition",
            None
        )

        if definition:

            definitions.append(
                definition
            )

    # --------------------------------------------------------
    # RENDER
    # --------------------------------------------------------

    return render(
        request,
        "learning/definition_list.html",
        {
            "subject":
                subject,

            "definitions":
                definitions,

            "subject_index":
                subject_index,

            "search_query":
                search_query,
        }
    )

# EDIT DEFINITION
# ============================================================

@login_required
def edit_definition(
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

    # ========================================================
    # FIND SUBJECT INDEX
    # ========================================================

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    subject = knowledge_unit.subject

    subject_index = None

    # --------------------------------------------------------
    # MATCH DATABASE ID
    # --------------------------------------------------------

    for index, subject_data in enumerate(subjects):

        if (
            subject_data.get("database_id")
            == subject.id
        ):

            subject_index = index

            break

    # --------------------------------------------------------
    # FALLBACK: MATCH SUBJECT NAME
    # --------------------------------------------------------

    if subject_index is None:

        for index, subject_data in enumerate(subjects):

            if (
                subject_data.get(
                    "name",
                    ""
                ).strip()
                == subject.name
            ):

                subject_index = index

                break

    # --------------------------------------------------------
    # FINAL FALLBACK
    # --------------------------------------------------------

    if subject_index is None:

        subject_index = 0

    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        term = request.POST.get(
            "term",
            ""
        ).strip()

        definition_text = request.POST.get(
            "definition",
            ""
        ).strip()

        difficulty = request.POST.get(
            "difficulty",
            knowledge_unit.difficulty
        )

        estimated_minutes = request.POST.get(
            "estimated_minutes",
            knowledge_unit.estimated_minutes
        )

        # ====================================================
        # VALIDATION
        # ====================================================

        if term and definition_text:

            # ------------------------------------------------
            # UPDATE KNOWLEDGE UNIT
            # ------------------------------------------------

            knowledge_unit.title = term

            try:
                knowledge_unit.difficulty = int(
                    difficulty
                )
            except (
                ValueError,
                TypeError
            ):
                knowledge_unit.difficulty = 1

            try:
                knowledge_unit.estimated_minutes = int(
                    estimated_minutes
                )
            except (
                ValueError,
                TypeError
            ):
                knowledge_unit.estimated_minutes = 2

            knowledge_unit.save()

            # ------------------------------------------------
            # UPDATE DEFINITION
            # ------------------------------------------------

            definition.term = term

            definition.definition = (
                definition_text
            )

            definition.save()

            return redirect(
                "definition_list",
                subject_id=subject.id
            )

    # ========================================================
    # DISPLAY EDIT PAGE
    # ========================================================

    return render(
        request,
        "learning/edit_definition.html",
        {
            "definition":
                definition,

            "subject":
                subject,

            "subject_index":
                subject_index,
        }
    )


# ============================================================
# DELETE DEFINITION
# ============================================================

@login_required
def delete_definition(
    request,
    definition_id
):

    definition = get_object_or_404(
        Definition,
        id=definition_id,
        knowledge_unit__subject__user=request.user
    )

    subject = definition.knowledge_unit.subject

    # ========================================================
    # ONLY DELETE THROUGH POST
    # ========================================================

    if request.method == "POST":

        knowledge_unit = (
            definition.knowledge_unit
        )

        # Deleting the KnowledgeUnit will also
        # remove the Definition because the
        # Definition belongs to it.

        knowledge_unit.delete()

        return redirect(
            "definition_list",
            subject_id=subject.id
        )

    # ========================================================
    # GET REQUEST
    # ========================================================

    return redirect(
        "definition_list",
        subject_id=subject.id
    )
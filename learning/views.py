from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from datetime import date, datetime, timedelta

import json
import random

from .forms import FormulaForm

from .models import (
    Subject,
    KnowledgeUnit,
    Formula,
    FormulaVariable,
    Definition,
    BulletList,
    BulletItem,
    StudentKnowledge,
)

from dashboard.models import (
    StudyAvailability,
    SubjectTextbook,
    SubjectRevisionPlan,
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
# LIST REVIEW HELPERS
# ============================================================

def normalize_list_answer(
    value
):
    """
    Make list answers case-insensitive and ignore
    unnecessary spaces.
    """

    return " ".join(
        str(
            value
            or ""
        )
        .strip()
        .casefold()
        .split()
    )


def get_list_hidden_count(
    total_items,
    mastery_level
):
    """
    Number of list items hidden at each mastery level.

    0/6 -> exactly 1 hidden item
    6/6 -> all items hidden

    Levels between 0 and 6 gradually increase
    the number of hidden items.
    """

    total_items = int(
        total_items
        or 0
    )

    mastery_level = int(
        mastery_level
        or 0
    )

    mastery_level = max(
        0,
        min(
            6,
            mastery_level
        )
    )

    if total_items <= 0:

        return 0

    if total_items == 1:

        return 1

    if mastery_level == 0:

        return 1

    if mastery_level >= 6:

        return total_items

    hidden_count = (
        1
        +
        (
            (
                total_items - 1
            )
            *
            mastery_level
            //
            6
        )
    )

    return max(
        1,
        min(
            hidden_count,
            total_items
        )
    )


# ============================================================
# REVIEW INDIVIDUAL LIST
# ============================================================

@login_required
def review_list(
    request,
    list_id
):

    # ========================================================
    # LIST
    # ========================================================

    bullet_list = get_object_or_404(
        BulletList.objects
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        ),
        id=list_id,
        knowledge_unit__subject__user=request.user,
        knowledge_unit__active=True,
    )

    knowledge_unit = (
        bullet_list.knowledge_unit
    )

    subject = (
        knowledge_unit.subject
    )

    # ========================================================
    # SUBJECT INDEX
    # ========================================================

    subject_index = (
        request.GET.get(
            "subject_index"
        )
        or
        request.POST.get(
            "subject_index"
        )
    )

    try:

        subject_index = int(
            subject_index
        )

    except (
        TypeError,
        ValueError
    ):

        subject_index = None

    # ========================================================
    # PROGRESS
    # ========================================================

    progress, created = (
        StudentKnowledge.objects
        .get_or_create(
            student=request.user,
            knowledge_unit=knowledge_unit,
        )
    )

    progress.mastery_level = max(
        0,
        min(
            6,
            int(
                progress.mastery_level
                or 0
            )
        )
    )

    # ========================================================
    # ITEMS
    # ========================================================

    items = list(
        bullet_list.items
        .all()
        .order_by(
            "order",
            "id",
        )
    )

    total_items = len(
        items
    )

    # ========================================================
    # CURRENT MASTERY PERCENTAGE
    # ========================================================

    mastery_percentage = round(
        (
            progress.mastery_level
            /
            6
        )
        * 100
    )

    # ========================================================
    # EMPTY LIST
    # ========================================================

    if total_items == 0:

        return render(
            request,
            "practice/list_review.html",
            {
                "bullet_list":
                    bullet_list,

                "subject":
                    subject,

                "subject_index":
                    subject_index,

                "progress":
                    progress,

                "mastery_level":
                    progress.mastery_level,

                "mastery_percentage":
                    mastery_percentage,

                "total_items":
                    0,

                "hidden_count":
                    0,

                "review_items":
                    [],

                "error":
                    (
                        "This list does not "
                        "contain any items."
                    ),

                "result":
                    None,

                "attempt_complete":
                    False,

                "correct_answers":
                    [],

                "next_list":
                    None,
            }
        )

    # ========================================================
    # NUMBER OF ITEMS TO HIDE
    # ========================================================

    hidden_count = (
        get_list_hidden_count(
            total_items,
            progress.mastery_level,
        )
    )

    # ========================================================
    # STATE
    # ========================================================

    result = None

    error = None

    attempt_complete = False

    correct_answers = []

    next_list = None

    hidden_item_ids = []

    submitted_answers = {}

    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        # ====================================================
        # GET HIDDEN IDS
        # ====================================================

        hidden_item_id_values = (
            request.POST.getlist(
                "hidden_item_id"
            )
        )

        for value in (
            hidden_item_id_values
        ):

            try:

                item_id = int(
                    value
                )

            except (
                TypeError,
                ValueError
            ):

                continue

            if (
                item_id
                not in hidden_item_ids
            ):

                hidden_item_ids.append(
                    item_id
                )

        # ====================================================
        # VALID IDS
        # ====================================================

        valid_item_ids = {
            item.id

            for item
            in items
        }

        hidden_item_ids = [
            item_id

            for item_id
            in hidden_item_ids

            if item_id
            in valid_item_ids
        ]

        # ====================================================
        # VALIDATE FORM
        # ====================================================

        if (
            len(
                hidden_item_ids
            )
            != hidden_count
        ):

            error = (
                "The review changed unexpectedly. "
                "Please reload the page and try again."
            )

        else:

            # =================================================
            # COLLECT EXPECTED ANSWERS
            # =================================================

            expected_answers = []

            student_answers = []

            for item in items:

                if (
                    item.id
                    not in hidden_item_ids
                ):

                    continue

                # --------------------------------------------
                # CORRECT ANSWER
                # --------------------------------------------

                expected_answers.append(
                    item.text
                )

                # --------------------------------------------
                # STUDENT ANSWER
                # --------------------------------------------

                answer_name = (
                    f"answer_{item.id}"
                )

                submitted_answer = (
                    request.POST.get(
                        answer_name,
                        ""
                    )
                )

                submitted_answers[
                    item.id
                ] = submitted_answer

                student_answers.append(
                    submitted_answer
                )

            # =================================================
            # NORMALIZE ALL ANSWERS
            # =================================================
            #
            # IMPORTANT:
            #
            # We compare the complete answer collections,
            # NOT the positions.
            #
            # Example:
            #
            # Correct:
            #
            # milk
            # honey
            # bread
            #
            # Student:
            #
            # bread
            # milk
            # honey
            #
            # = CORRECT
            # =================================================

            normalized_expected = sorted(
                normalize_list_answer(
                    answer
                )

                for answer
                in expected_answers
            )

            normalized_student = sorted(
                normalize_list_answer(
                    answer
                )

                for answer
                in student_answers
            )

            all_correct = (
                normalized_student
                ==
                normalized_expected
            )

            # =================================================
            # REVIEW ATTEMPT COMPLETE
            # =================================================

            attempt_complete = True

            now = timezone.now()

            progress.review_count = (
                progress.review_count
                +
                1
            )

            progress.last_reviewed = (
                now
            )

            # =================================================
            # CORRECT
            # =================================================

            if all_correct:

                result = "correct"

                progress.correct_count = (
                    progress.correct_count
                    +
                    1
                )

                progress.mastery_level = min(
                    6,
                    (
                        progress.mastery_level
                        +
                        1
                    )
                )

            # =================================================
            # INCORRECT
            # =================================================

            else:

                result = "incorrect"

                progress.incorrect_count = (
                    progress.incorrect_count
                    +
                    1
                )

                progress.mastery_level = max(
                    0,
                    (
                        progress.mastery_level
                        -
                        1
                    )
                )

                # --------------------------------------------
                # SHOW CORRECT ANSWERS
                # --------------------------------------------

                correct_answers = (
                    expected_answers
                )

            # =================================================
            # NEXT REVIEW
            # =================================================

            interval_days = (
                get_review_interval(
                    progress.mastery_level
                )
            )

            progress.next_review = (
                now
                +
                timedelta(
                    days=interval_days
                )
            )

            progress.save()

            # =================================================
            # FIND NEXT DUE LIST
            # =================================================

            today = timezone.localdate()

            possible_next_lists = (
                BulletList.objects
                .filter(
                    knowledge_unit__subject=subject,
                    knowledge_unit__active=True,
                )
                .select_related(
                    "knowledge_unit"
                )
                .exclude(
                    id=bullet_list.id
                )
                .order_by(
                    "knowledge_unit__created",
                    "id",
                )
            )

            for candidate in (
                possible_next_lists
            ):

                candidate_progress = (
                    StudentKnowledge.objects
                    .filter(
                        student=request.user,
                        knowledge_unit=(
                            candidate.knowledge_unit
                        ),
                    )
                    .first()
                )

                candidate_is_due = False

                if candidate_progress is None:

                    candidate_is_due = True

                elif (
                    candidate_progress.next_review
                    is None
                ):

                    candidate_is_due = True

                elif (
                    candidate_progress
                    .next_review
                    .date()
                    <= today
                ):

                    candidate_is_due = True

                if candidate_is_due:

                    next_list = (
                        candidate
                    )

                    break

            # =================================================
            # UPDATED MASTERY
            # =================================================

            mastery_percentage = round(
                (
                    progress.mastery_level
                    /
                    6
                )
                * 100
            )

            # =================================================
            # SHOW RESULT SCREEN
            # =================================================

            return render(
                request,
                "practice/list_review.html",
                {
                    "bullet_list":
                        bullet_list,

                    "subject":
                        subject,

                    "subject_index":
                        subject_index,

                    "progress":
                        progress,

                    "mastery_level":
                        progress.mastery_level,

                    "mastery_percentage":
                        mastery_percentage,

                    "total_items":
                        total_items,

                    "hidden_count":
                        hidden_count,

                    "review_items":
                        [],

                    "error":
                        None,

                    "result":
                        result,

                    "attempt_complete":
                        True,

                    "correct_answers":
                        correct_answers,

                    "next_list":
                        next_list,
                }
            )

    # ========================================================
    # GET
    #
    # RANDOMLY HIDE ITEMS
    # ========================================================

    else:

        hidden_items = (
            random.sample(
                items,
                hidden_count
            )
        )

        hidden_item_ids = [
            item.id

            for item
            in hidden_items
        ]

    # ========================================================
    # BUILD REVIEW ITEMS
    # ========================================================

    hidden_item_id_set = set(
        hidden_item_ids
    )

    review_items = []

    for item in items:

        is_hidden = (
            item.id
            in hidden_item_id_set
        )

        review_items.append(
            {
                "item":
                    item,

                "hidden":
                    is_hidden,

                "input_name":
                    f"answer_{item.id}",

                "submitted_answer":
                    submitted_answers.get(
                        item.id,
                        ""
                    ),
            }
        )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "practice/list_review.html",
        {
            "bullet_list":
                bullet_list,

            "subject":
                subject,

            "subject_index":
                subject_index,

            "progress":
                progress,

            "mastery_level":
                progress.mastery_level,

            "mastery_percentage":
                mastery_percentage,

            "total_items":
                total_items,

            "hidden_count":
                hidden_count,

            "review_items":
                review_items,

            "error":
                error,

            "result":
                result,

            "attempt_complete":
                attempt_complete,

            "correct_answers":
                correct_answers,

            "next_list":
                next_list,
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

# ============================================================
# LIST REVIEW LIST
# ============================================================

@login_required
def list_review_list(
    request,
    subject_index
):

    # ========================================================
    # SESSION SUBJECTS
    # ========================================================

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    # ========================================================
    # VALIDATE SUBJECT INDEX
    # ========================================================

    try:

        subject_index = int(
            subject_index
        )

    except (
        TypeError,
        ValueError
    ):

        return redirect(
            "goals"
        )

    if (
        subject_index < 0
        or
        subject_index >= len(subjects)
    ):

        return redirect(
            "goals"
        )

    subject_data = (
        subjects[
            subject_index
        ]
    )

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
            Subject.objects
            .filter(
                id=database_subject_id,
                user=request.user,
            )
            .first()
        )

    # --------------------------------------------------------
    # FALLBACK TO NAME
    # --------------------------------------------------------

    if not database_subject:

        subject_name = (
            subject_data.get(
                "name",
                ""
            )
            .strip()
        )

        if subject_name:

            database_subject = (
                Subject.objects
                .filter(
                    user=request.user,
                    name=subject_name,
                )
                .first()
            )

    if not database_subject:

        return redirect(
            "subject_detail",
            subject_index=subject_index
        )

    # ========================================================
    # TODAY
    # ========================================================

    today = timezone.localdate()

    # ========================================================
    # ALL ACTIVE LISTS FOR SUBJECT
    # ========================================================

    bullet_lists = (
        BulletList.objects
        .filter(
            knowledge_unit__subject=database_subject,
            knowledge_unit__knowledge_type=(
                KnowledgeUnit
                .KnowledgeType
                .BULLET_LIST
            ),
            knowledge_unit__active=True,
        )
        .select_related(
            "knowledge_unit"
        )
        .prefetch_related(
            "items"
        )
        .order_by(
            "knowledge_unit__created",
            "id",
        )
    )

    # ========================================================
    # ONLY LISTS DUE TODAY
    # ========================================================

    due_lists = []

    for bullet_list in bullet_lists:

        progress = (
            StudentKnowledge.objects
            .filter(
                student=request.user,
                knowledge_unit=(
                    bullet_list.knowledge_unit
                ),
            )
            .first()
        )

        is_due = False

        if progress is None:

            is_due = True

        elif progress.next_review is None:

            is_due = True

        elif (
            progress.next_review.date()
            <= today
        ):

            is_due = True

        if is_due:

            due_lists.append(
                bullet_list
            )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "learning/list_review_list.html",
        {
            "subject":
                database_subject,

            "subject_data":
                subject_data,

            "subject_index":
                subject_index,

            "due_lists":
                due_lists,

            "due_list_count":
                len(
                    due_lists
                ),
        }
    )

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

    # ====================================================
    # LISTS
    # ====================================================

    bullet_lists = (
        BulletList.objects
        .filter(
            knowledge_unit__subject=database_subject,
            knowledge_unit__knowledge_type=(
                KnowledgeUnit
                .KnowledgeType
                .BULLET_LIST
            ),
            knowledge_unit__active=True,
        )
        .select_related(
            "knowledge_unit"
        )
        .prefetch_related(
            "items"
        )
        .order_by(
            "knowledge_unit__created",
            "id",
        )
    )

    for bullet_list in (
        bullet_lists
    ):

        progress = (
            StudentKnowledge.objects
            .filter(
                student=request.user,
                knowledge_unit=(
                    bullet_list.knowledge_unit
                ),
            )
            .first()
        )

        is_due = False

        if progress is None:

            is_due = True

        elif progress.next_review is None:

            is_due = True

        elif (
            progress.next_review.date()
            <= today
        ):

            is_due = True

        if is_due:

            due_bullet_lists.append(
                bullet_list
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

    return redirect(
        "practice_definition_review",
        definition_id=definition.id
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


# ============================================================
# BOOK SUMMARY HELPERS
# ============================================================

def summary_duration_to_minutes(
    value
):

    if not value:
        return 0

    try:

        hours_text, minutes_text = (
            str(value).split(
                ":",
                1
            )
        )

        hours = int(
            hours_text
        )

        minutes = int(
            minutes_text
        )

        if (
            hours < 0
            or
            hours > 24
            or
            minutes < 0
            or
            minutes > 59
        ):

            return 0

        if (
            hours == 24
            and
            minutes != 0
        ):

            return 0

        return (
            hours * 60
            +
            minutes
        )

    except (
        TypeError,
        ValueError
    ):

        return 0


def summary_format_minutes(
    total_minutes
):

    total_minutes = int(
        total_minutes
        or 0
    )

    hours = (
        total_minutes
        // 60
    )

    minutes = (
        total_minutes
        % 60
    )

    if (
        hours > 0
        and
        minutes > 0
    ):

        return (
            f"{hours}h "
            f"{minutes}m"
        )

    if hours > 0:

        return (
            f"{hours}h"
        )

    return (
        f"{minutes}m"
    )


def get_summary_weekday_schedule(
    availability
):

    schedule = {

        0: {
            "enabled": False,
            "minutes": 0,
        },

        1: {
            "enabled": False,
            "minutes": 0,
        },

        2: {
            "enabled": False,
            "minutes": 0,
        },

        3: {
            "enabled": False,
            "minutes": 0,
        },

        4: {
            "enabled": False,
            "minutes": 0,
        },

        5: {
            "enabled": False,
            "minutes": 0,
        },

        6: {
            "enabled": False,
            "minutes": 0,
        },

    }

    if not availability:

        return schedule

    fields = {

        0: (
            "monday_enabled",
            "monday_time",
        ),

        1: (
            "tuesday_enabled",
            "tuesday_time",
        ),

        2: (
            "wednesday_enabled",
            "wednesday_time",
        ),

        3: (
            "thursday_enabled",
            "thursday_time",
        ),

        4: (
            "friday_enabled",
            "friday_time",
        ),

        5: (
            "saturday_enabled",
            "saturday_time",
        ),

        6: (
            "sunday_enabled",
            "sunday_time",
        ),

    }

    for (
        weekday,
        field_names
    ) in fields.items():

        enabled_field = (
            field_names[0]
        )

        time_field = (
            field_names[1]
        )

        enabled = bool(
            getattr(
                availability,
                enabled_field,
                False
            )
        )

        minutes = 0

        if enabled:

            minutes = (
                summary_duration_to_minutes(
                    getattr(
                        availability,
                        time_field,
                        ""
                    )
                )
            )

        schedule[
            weekday
        ][
            "enabled"
        ] = enabled

        schedule[
            weekday
        ][
            "minutes"
        ] = minutes

    return schedule


def parse_summary_exam_date(
    subject_data
):

    exam_date_value = (
        subject_data.get(
            "exam_date"
        )
    )

    if not exam_date_value:

        return None

    try:

        if isinstance(
            exam_date_value,
            datetime
        ):

            return (
                exam_date_value.date()
            )

        if isinstance(
            exam_date_value,
            date
        ):

            return exam_date_value

        return date.fromisoformat(
            str(
                exam_date_value
            )[:10]
        )

    except (
        TypeError,
        ValueError
    ):

        return None


def calculate_book_summary_targets(
    request,
    subject,
    subject_data,
    textbooks,
):

    today = timezone.localdate()

    parsed_exam_date = (
        parse_summary_exam_date(
            subject_data
        )
    )

    # ========================================================
    # AVAILABILITY
    # ========================================================

    availability = (
        StudyAvailability.objects
        .filter(
            user=request.user
        )
        .first()
    )

    weekday_schedule = (
        get_summary_weekday_schedule(
            availability
        )
    )

    # ========================================================
    # BUILD REMAINING STUDY DATES
    # ========================================================

    remaining_study_dates = []

    if (
        parsed_exam_date
        and
        parsed_exam_date > today
    ):

        current_date = today

        while (
            current_date
            < parsed_exam_date
        ):

            weekday = (
                current_date.weekday()
            )

            if (
                weekday_schedule[
                    weekday
                ][
                    "enabled"
                ]
            ):

                remaining_study_dates.append(
                    current_date
                )

            current_date += timedelta(
                days=1
            )

    # ========================================================
    # REVISION DAYS
    # ========================================================

    revision_days = 0

    revision_plan = (
        SubjectRevisionPlan.objects
        .filter(
            subject=subject
        )
        .first()
    )

    if (
        revision_plan
        and
        revision_plan.revision_days
        is not None
    ):

        revision_days = int(
            revision_plan.revision_days
        )

    revision_days = max(
        0,
        min(
            revision_days,
            len(
                remaining_study_dates
            )
        )
    )

    # ========================================================
    # REMOVE REVISION PERIOD
    # ========================================================

    if revision_days > 0:

        learning_dates = (
            remaining_study_dates[
                :-revision_days
            ]
        )

    else:

        learning_dates = list(
            remaining_study_dates
        )

    # ========================================================
    # ONLY LEARNING DAYS WITH REAL STUDY TIME
    # ========================================================

    learning_dates_with_time = []

    for learning_date in (
        learning_dates
    ):

        weekday = (
            learning_date.weekday()
        )

        minutes = (
            weekday_schedule[
                weekday
            ][
                "minutes"
            ]
        )

        if minutes > 0:

            learning_dates_with_time.append(
                learning_date
            )

    # ========================================================
    # TOTAL REMAINING LEARNING TIME
    # ========================================================

    total_learning_minutes = sum(

        weekday_schedule[
            learning_date.weekday()
        ][
            "minutes"
        ]

        for learning_date
        in learning_dates_with_time

    )

    today_minutes = (
        weekday_schedule[
            today.weekday()
        ][
            "minutes"
        ]
    )

    today_is_learning_day = (
        today
        in learning_dates_with_time
        and
        today_minutes > 0
        and
        total_learning_minutes > 0
    )

    # ========================================================
    # BUILD BOOK TARGETS
    # ========================================================

    book_items = []

    for textbook in textbooks:

        pages_summarized = min(
            textbook.pages_summarized,
            textbook.page_count,
        )

        remaining_pages = max(
            0,
            (
                textbook.page_count
                -
                pages_summarized
            )
        )

        completed_today = (
            textbook.last_summary_date
            == today
        )

        target_pages = 0

        exact_target = 0

        # ----------------------------------------------------
        # TODAY'S TARGET
        #
        # Remaining pages are distributed according to
        # today's share of the remaining learning time.
        #
        # Tomorrow this calculation automatically uses:
        #
        # - fewer remaining pages
        # - less remaining learning time
        #
        # therefore automatically rebalancing the plan.
        # ----------------------------------------------------

        if (
            remaining_pages > 0
            and
            today_is_learning_day
            and
            not completed_today
        ):

            exact_target = (
                remaining_pages
                *
                (
                    today_minutes
                    /
                    total_learning_minutes
                )
            )

            target_pages = int(
                exact_target
                + 0.5
            )

            target_pages = max(
                1,
                target_pages
            )

            target_pages = min(
                target_pages,
                remaining_pages
            )

        # ----------------------------------------------------
        # PROGRESS PERCENT
        # ----------------------------------------------------

        if textbook.page_count > 0:

            progress_percentage = round(
                (
                    pages_summarized
                    /
                    textbook.page_count
                )
                * 100
            )

        else:

            progress_percentage = 0

        book_items.append(
            {
                "textbook":
                    textbook,

                "pages_summarized":
                    pages_summarized,

                "remaining_pages":
                    remaining_pages,

                "target_pages":
                    target_pages,

                "exact_target":
                    round(
                        exact_target,
                        2
                    ),

                "completed_today":
                    completed_today,

                "complete":
                    (
                        remaining_pages
                        == 0
                    ),

                "progress_percentage":
                    progress_percentage,
            }
        )

    return {
        "today":
            today,

        "parsed_exam_date":
            parsed_exam_date,

        "revision_days":
            revision_days,

        "learning_days_left":
            len(
                learning_dates
            ),

        "today_is_learning_day":
            today_is_learning_day,

        "today_minutes":
            today_minutes,

        "total_learning_minutes":
            total_learning_minutes,

        "today_study_time":
            summary_format_minutes(
                today_minutes
            ),

        "total_learning_time":
            summary_format_minutes(
                total_learning_minutes
            ),

        "book_items":
            book_items,
    }


# ============================================================
# BOOK SUMMARY
# ============================================================

@login_required
def book_summary(
    request,
    subject_index
):

    # ========================================================
    # SESSION SUBJECTS
    # ========================================================

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    # ========================================================
    # VALIDATE SUBJECT INDEX
    # ========================================================

    try:

        subject_index = int(
            subject_index
        )

    except (
        TypeError,
        ValueError
    ):

        return redirect(
            "goals"
        )

    if (
        subject_index < 0
        or
        subject_index >= len(subjects)
    ):

        return redirect(
            "goals"
        )

    subject_data = (
        subjects[
            subject_index
        ]
    )

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
            Subject.objects
            .filter(
                id=database_subject_id,
                user=request.user,
            )
            .first()
        )

    # --------------------------------------------------------
    # FALLBACK TO NAME
    # --------------------------------------------------------

    if not database_subject:

        subject_name = (
            subject_data.get(
                "name",
                ""
            )
            .strip()
        )

        if subject_name:

            database_subject = (
                Subject.objects
                .filter(
                    user=request.user,
                    name=subject_name,
                )
                .first()
            )

    if not database_subject:

        return redirect(
            "subject_detail",
            subject_index=subject_index
        )

    # ========================================================
    # TEXTBOOKS
    # ========================================================

    textbooks = list(
        SubjectTextbook.objects
        .filter(
            subject=database_subject
        )
        .order_by(
            "created",
            "id",
        )
    )

    # ========================================================
    # CALCULATE CURRENT TARGETS
    # ========================================================

    schedule_data = (
        calculate_book_summary_targets(
            request=request,
            subject=database_subject,
            subject_data=subject_data,
            textbooks=textbooks,
        )
    )

    book_items = (
        schedule_data[
            "book_items"
        ]
    )

    # Fast lookup for POST actions.

    book_item_lookup = {
        item[
            "textbook"
        ].id: item
        for item
        in book_items
    }

    error = None

    custom_book_id = None

    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        action = request.POST.get(
            "action",
            ""
        )

        textbook_id_raw = (
            request.POST.get(
                "textbook_id",
                ""
            )
            .strip()
        )

        try:

            textbook_id = int(
                textbook_id_raw
            )

        except (
            TypeError,
            ValueError
        ):

            textbook_id = None

        # ----------------------------------------------------
        # FIND TEXTBOOK
        # ----------------------------------------------------

        textbook = None

        if textbook_id:

            textbook = (
                SubjectTextbook.objects
                .filter(
                    id=textbook_id,
                    subject=database_subject,
                )
                .first()
            )

        if not textbook:

            error = (
                "Could not find that textbook."
            )

        else:

            item = (
                book_item_lookup.get(
                    textbook.id
                )
            )

            if not item:

                error = (
                    "Could not calculate "
                    "the textbook target."
                )

            elif item[
                "complete"
            ]:

                error = (
                    "This textbook has already "
                    "been completely summarized."
                )

            elif item[
                "completed_today"
            ]:

                error = (
                    "Today's pages for this "
                    "textbook have already "
                    "been saved."
                )

            # =================================================
            # COMPLETE TODAY'S TARGET
            # =================================================

            elif action == "complete_target":

                target_pages = (
                    item[
                        "target_pages"
                    ]
                )

                if target_pages <= 0:

                    error = (
                        "There are no pages "
                        "scheduled for this "
                        "textbook today."
                    )

                else:

                    textbook.pages_summarized = min(
                        textbook.page_count,
                        (
                            textbook.pages_summarized
                            +
                            target_pages
                        )
                    )

                    textbook.last_summary_date = (
                        timezone.localdate()
                    )

                    textbook.save(
                        update_fields=[
                            "pages_summarized",
                            "last_summary_date",
                        ]
                    )

                    return redirect(
                        "book_summary",
                        subject_index=subject_index
                    )

            # =================================================
            # CUSTOM PAGE AMOUNT
            # =================================================

            elif action == "save_custom_pages":

                custom_book_id = (
                    textbook.id
                )

                custom_pages_raw = (
                    request.POST.get(
                        "custom_pages",
                        ""
                    )
                    .strip()
                )

                try:

                    custom_pages = int(
                        custom_pages_raw
                    )

                except (
                    TypeError,
                    ValueError
                ):

                    custom_pages = 0

                if custom_pages <= 0:

                    error = (
                        "Enter a page amount "
                        "greater than 0."
                    )

                elif (
                    custom_pages
                    >
                    item[
                        "remaining_pages"
                    ]
                ):

                    error = (
                        f"Only "
                        f"{item['remaining_pages']} "
                        f"pages remain in "
                        f"{textbook.name}."
                    )

                else:

                    textbook.pages_summarized = (
                        textbook.pages_summarized
                        +
                        custom_pages
                    )

                    textbook.last_summary_date = (
                        timezone.localdate()
                    )

                    textbook.save(
                        update_fields=[
                            "pages_summarized",
                            "last_summary_date",
                        ]
                    )

                    return redirect(
                        "book_summary",
                        subject_index=subject_index
                    )

    # ========================================================
    # TOTALS
    # ========================================================

    total_pages = sum(
        textbook.page_count
        for textbook
        in textbooks
    )

    total_pages_summarized = sum(
        min(
            textbook.pages_summarized,
            textbook.page_count
        )
        for textbook
        in textbooks
    )

    total_pages_remaining = max(
        0,
        (
            total_pages
            -
            total_pages_summarized
        )
    )

    target_total_today = sum(
        item[
            "target_pages"
        ]
        for item
        in book_items
    )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "learning/book_summary.html",
        {
            "subject":
                database_subject,

            "subject_data":
                subject_data,

            "subject_index":
                subject_index,

            "book_items":
                book_items,

            "total_pages":
                total_pages,

            "total_pages_summarized":
                total_pages_summarized,

            "total_pages_remaining":
                total_pages_remaining,

            "target_total_today":
                target_total_today,

            "today_is_learning_day":
                schedule_data[
                    "today_is_learning_day"
                ],

            "today_study_time":
                schedule_data[
                    "today_study_time"
                ],

            "total_learning_time":
                schedule_data[
                    "total_learning_time"
                ],

            "learning_days_left":
                schedule_data[
                    "learning_days_left"
                ],

            "revision_days":
                schedule_data[
                    "revision_days"
                ],

            "error":
                error,

            "custom_book_id":
                custom_book_id,
        }
    )



# ============================================================
# CREATE LIST
# ============================================================

@login_required
def create_list(
    request,
    subject_id
):

    # ========================================================
    # SUBJECT
    # ========================================================

    subject = get_object_or_404(
        Subject,
        id=subject_id,
        user=request.user,
    )

    # ========================================================
    # SUBJECT INDEX
    # ========================================================

    subject_index = (
        request.GET.get(
            "subject_index"
        )
        or
        request.POST.get(
            "subject_index"
        )
    )

    # ========================================================
    # TEXTBOOKS
    # ========================================================

    textbooks = (
        SubjectTextbook.objects
        .filter(
            subject=subject
        )
        .order_by(
            "created",
            "id",
        )
    )

    # ========================================================
    # FORM VALUES
    # ========================================================

    list_name = ""

    selected_book = ""

    chapter = ""

    submitted_items = []

    error = None

    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        # ----------------------------------------------------
        # LIST NAME / DESCRIPTION
        # ----------------------------------------------------

        list_name = (
            request.POST.get(
                "list_name",
                ""
            )
            .strip()
        )

        # ----------------------------------------------------
        # OPTIONAL DETAILS
        # ----------------------------------------------------

        selected_book = (
            request.POST.get(
                "book_name",
                ""
            )
            .strip()
        )

        chapter = (
            request.POST.get(
                "chapter",
                ""
            )
            .strip()
        )

        # ----------------------------------------------------
        # ITEM ARRAYS
        # ----------------------------------------------------

        item_texts = (
            request.POST.getlist(
                "item_text"
            )
        )

        item_descriptions = (
            request.POST.getlist(
                "item_description"
            )
        )

        # ----------------------------------------------------
        # REBUILD ITEMS
        #
        # This is also used if validation fails so the
        # student's entered values stay on screen.
        # ----------------------------------------------------

        submitted_items = []

        for index, item_text in enumerate(
            item_texts
        ):

            item_text = (
                item_text.strip()
            )

            item_description = ""

            if (
                index
                <
                len(
                    item_descriptions
                )
            ):

                item_description = (
                    item_descriptions[
                        index
                    ]
                    .strip()
                )

            submitted_items.append(
                {
                    "text":
                        item_text,

                    "description":
                        item_description,
                }
            )

        # ====================================================
        # VALIDATE LIST NAME
        # ====================================================

        if not list_name:

            error = (
                "Enter a name or description "
                "for the list."
            )

        # ====================================================
        # VALIDATE BOOK
        # ====================================================

        if (
            error is None
            and
            selected_book
        ):

            valid_book = (
                textbooks
                .filter(
                    name=selected_book
                )
                .exists()
            )

            if not valid_book:

                error = (
                    "The selected textbook "
                    "does not belong to this subject."
                )

        # ====================================================
        # REMOVE COMPLETELY EMPTY ITEMS
        # ====================================================

        valid_items = []

        for item in submitted_items:

            if item[
                "text"
            ]:

                valid_items.append(
                    item
                )

        # ====================================================
        # REQUIRE AT LEAST ONE LIST ITEM
        # ====================================================

        if (
            error is None
            and
            not valid_items
        ):

            error = (
                "Add at least one item "
                "to the list."
            )

        # ====================================================
        # CREATE
        # ====================================================

        if error is None:

            # ------------------------------------------------
            # KNOWLEDGE UNIT
            # ------------------------------------------------

            knowledge_unit = (
                KnowledgeUnit.objects.create(
                    subject=subject,
                    title=list_name,
                    knowledge_type=(
                        KnowledgeUnit
                        .KnowledgeType
                        .BULLET_LIST
                    ),
                    difficulty=1,
                    estimated_minutes=max(
                        2,
                        len(
                            valid_items
                        )
                    ),
                    active=True,
                )
            )

            # ------------------------------------------------
            # BULLET LIST
            # ------------------------------------------------

            bullet_list = (
                BulletList.objects.create(
                    knowledge_unit=knowledge_unit,
                    question=list_name,
                    book_name=selected_book,
                    chapter=chapter,
                )
            )

            # ------------------------------------------------
            # ITEMS
            # ------------------------------------------------

            for order, item in enumerate(
                valid_items,
                start=1,
            ):

                BulletItem.objects.create(
                    bullet_list=bullet_list,
                    text=item[
                        "text"
                    ],
                    description=item[
                        "description"
                    ],
                    order=order,
                )

            # ------------------------------------------------
            # RETURN TO SUBJECT
            # ------------------------------------------------

            if subject_index is not None:

                return redirect(
                    "subject_detail",
                    subject_index=subject_index
                )

            return redirect(
                "goals"
            )

    # ========================================================
    # DEFAULT EMPTY ITEMS
    # ========================================================

    if not submitted_items:

        submitted_items = [
            {
                "text":
                    "",

                "description":
                    "",
            },
            {
                "text":
                    "",

                "description":
                    "",
            },
            {
                "text":
                    "",

                "description":
                    "",
            },
        ]

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "learning/create_list.html",
        {
            "subject":
                subject,

            "subject_index":
                subject_index,

            "textbooks":
                textbooks,

            "list_name":
                list_name,

            "selected_book":
                selected_book,

            "chapter":
                chapter,

            "submitted_items":
                submitted_items,

            "error":
                error,
        }
    )
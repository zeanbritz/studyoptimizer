from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    render,
    redirect,
    get_object_or_404,
)
from django.urls import reverse
from django.utils import timezone

import json
import random

from learning.models import (
    Formula,
    KnowledgeUnit,
    StudentKnowledge,
    FormulaElementPerformance,
)


# ============================================================
# GET ALL FORMULA ELEMENTS
# ============================================================

def get_all_elements(elements):
    """
    Recursively collect every testable element in the formula.

    Elements inside fractions are also collected.

    The "=" operator is excluded because the student
    should not be tested on it.
    """

    result = []

    for element in elements:

        element_type = element.get("type")

        value = str(
            element.get(
                "value",
                ""
            )
        ).strip()

        # ----------------------------------------------------
        # DO NOT TEST "="
        # ----------------------------------------------------

        if (
            element_type == "operator"
            and value == "="
        ):

            continue

        # ----------------------------------------------------
        # FRACTION
        # ----------------------------------------------------

        if element_type == "fraction":

            result.extend(
                get_all_elements(
                    element.get(
                        "numerator",
                        []
                    )
                )
            )

            result.extend(
                get_all_elements(
                    element.get(
                        "denominator",
                        []
                    )
                )
            )

        else:

            result.append(
                element
            )

    return result


# ============================================================
# FIND ELEMENT BY ID
# ============================================================

def find_element(
    elements,
    element_id
):
    """
    Recursively find a formula element by its ID.

    This also searches inside fractions.
    """

    for element in elements:

        if str(
            element.get(
                "id"
            )
        ) == str(
            element_id
        ):

            return element

        # ----------------------------------------------------
        # SEARCH INSIDE FRACTION
        # ----------------------------------------------------

        if element.get(
            "type"
        ) == "fraction":

            found = find_element(
                element.get(
                    "numerator",
                    []
                ),
                element_id
            )

            if found:

                return found

            found = find_element(
                element.get(
                    "denominator",
                    []
                ),
                element_id
            )

            if found:

                return found

    return None


# ============================================================
# MASTERY -> HIDDEN PERCENTAGE
# ============================================================

def get_hidden_percentage(
    mastery_level
):
    """
    Determines approximately how much of the formula
    should be hidden at each mastery level.
    """

    percentages = {
        0: 10,
        1: 15,
        2: 30,
        3: 45,
        4: 60,
        5: 80,
        6: 100,
    }

    return percentages.get(
        mastery_level,
        15
    )


# ============================================================
# REVIEW INTERVAL
# ============================================================

def get_formula_review_interval(
    mastery_level
):
    """
    Number of days before the formula becomes due again.
    """

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
# RECORD ELEMENT PERFORMANCE
# ============================================================

def record_element_performance(
    formula,
    element,
    is_correct
):
    """
    Record whether the student answered one specific
    formula element correctly or incorrectly.
    """

    element_id = str(
        element.get(
            "id",
            ""
        )
    )

    if not element_id:

        return

    element_type = (
        element.get(
            "type",
            ""
        )
    )

    value = str(
        element.get(
            "value",
            ""
        )
    )

    performance, created = (
        FormulaElementPerformance.objects
        .get_or_create(
            formula=formula,
            element_id=element_id,
            defaults={
                "element_type":
                    element_type,

                "value":
                    value,
            }
        )
    )

    # --------------------------------------------------------
    # KEEP STORED DATA SYNCHRONIZED
    # --------------------------------------------------------

    performance.element_type = (
        element_type
    )

    performance.value = value

    performance.last_reviewed = (
        timezone.now()
    )

    # --------------------------------------------------------
    # CORRECT / INCORRECT
    # --------------------------------------------------------

    if is_correct:

        performance.correct_count += 1

    else:

        performance.incorrect_count += 1

    performance.save()


# ============================================================
# CHOOSE ELEMENTS TO HIDE
# ============================================================

def choose_hidden_elements(
    all_elements,
    mastery_level,
    formula,
    previous_ids=None
):
    """
    Choose which formula elements should be hidden.

    Approximately:

        70% weaker elements
        30% random elements

    Previously tested elements are avoided where possible.

    At mastery level 6, all testable elements are hidden.
    """

    if not all_elements:

        return []

    percentage = (
        get_hidden_percentage(
            mastery_level
        )
    )

    # ========================================================
    # MASTERY LEVEL 6
    # ========================================================

    if percentage >= 100:

        return all_elements.copy()

    # ========================================================
    # NUMBER OF ELEMENTS TO HIDE
    # ========================================================

    number_to_hide = round(
        len(all_elements)
        * percentage
        / 100
    )

    # Always test at least one element.

    number_to_hide = max(
        1,
        number_to_hide
    )

    number_to_hide = min(
        number_to_hide,
        len(all_elements)
    )

    previous_ids = (
        previous_ids
        or []
    )

    # ========================================================
    # GET PERFORMANCE DATA
    # ========================================================

    performance_records = (
        FormulaElementPerformance.objects
        .filter(
            formula=formula
        )
    )

    performance_map = {
        str(
            record.element_id
        ):
            record

        for record
        in performance_records
    }

    # ========================================================
    # CALCULATE WEAKNESS
    # ========================================================

    weighted_elements = []

    for element in all_elements:

        element_id = str(
            element.get(
                "id"
            )
        )

        record = (
            performance_map.get(
                element_id
            )
        )

        # ----------------------------------------------------
        # NEVER TESTED
        # ----------------------------------------------------

        if not record:

            weakness = 1.0

        else:

            total = (
                record.correct_count
                + record.incorrect_count
            )

            if total == 0:

                weakness = 1.0

            else:

                accuracy = (
                    record.correct_count
                    / total
                )

                weakness = (
                    1
                    - accuracy
                )

        weighted_elements.append(
            (
                element,
                weakness
            )
        )

    # ========================================================
    # AVOID IMMEDIATELY REPEATING ELEMENTS
    # ========================================================

    available = [
        item
        for item
        in weighted_elements
        if str(
            item[0].get(
                "id"
            )
        ) not in previous_ids
    ]

    # --------------------------------------------------------
    # NOT ENOUGH ALTERNATIVES
    # --------------------------------------------------------

    if len(
        available
    ) < number_to_hide:

        available = (
            weighted_elements
        )

    # ========================================================
    # SPLIT SELECTION
    # ========================================================

    weak_count = round(
        number_to_hide
        * 0.7
    )

    weak_count = min(
        weak_count,
        number_to_hide
    )

    random_count = (
        number_to_hide
        - weak_count
    )

    # ========================================================
    # SORT BY WEAKNESS
    # ========================================================

    sorted_elements = sorted(
        available,
        key=lambda item: item[1],
        reverse=True
    )

    weak_candidates = [
        element

        for element, weakness
        in sorted_elements

        if weakness > 0
    ]

    selected = []

    # ========================================================
    # SELECT WEAK ELEMENTS
    # ========================================================

    if (
        weak_candidates
        and weak_count > 0
    ):

        weak_pool_size = max(
            weak_count,

            min(
                len(
                    weak_candidates
                ),

                weak_count
                * 2
            )
        )

        weak_pool = (
            weak_candidates[
                :weak_pool_size
            ]
        )

        selected.extend(
            random.sample(
                weak_pool,

                min(
                    weak_count,
                    len(
                        weak_pool
                    )
                )
            )
        )

    # ========================================================
    # SELECT RANDOM ELEMENTS
    # ========================================================

    remaining = [
        element

        for element, weakness
        in available

        if element not in selected
    ]

    if (
        remaining
        and random_count > 0
    ):

        selected.extend(
            random.sample(
                remaining,

                min(
                    random_count,
                    len(
                        remaining
                    )
                )
            )
        )

    # ========================================================
    # FILL REMAINING SPACES
    # ========================================================

    if len(
        selected
    ) < number_to_hide:

        remaining = [
            element

            for element, weakness
            in available

            if element not in selected
        ]

        if remaining:

            selected.extend(
                random.sample(
                    remaining,

                    min(
                        number_to_hide
                        - len(
                            selected
                        ),

                        len(
                            remaining
                        )
                    )
                )
            )

    return selected[
        :number_to_hide
    ]


# ============================================================
# GET NEXT GLOBAL FORMULA
# ============================================================

def get_next_global_formula(
    user,
    current_formula,
):
    """
    Used when the student entered through:

        Review -> Formulas

    Global review can move between subjects.

    When the end is reached it wraps back to the first
    available formula so the student can continue until
    they press Finish Review.
    """

    formulas = (
        Formula.objects
        .filter(
            knowledge_unit__subject__user=user,

            knowledge_unit__knowledge_type=(
                KnowledgeUnit
                .KnowledgeType
                .FORMULA
            ),

            knowledge_unit__active=True,
        )
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        )
        .order_by(
            "id"
        )
    )

    # --------------------------------------------------------
    # FIND NEXT FORMULA
    # --------------------------------------------------------

    next_formula = (
        formulas
        .filter(
            id__gt=current_formula.id
        )
        .first()
    )

    if next_formula is not None:

        return next_formula

    # --------------------------------------------------------
    # END OF LIST
    #
    # GLOBAL REVIEW MAY WRAP.
    # --------------------------------------------------------

    return (
        formulas
        .exclude(
            id=current_formula.id
        )
        .first()
    )


# ============================================================
# BUILD GLOBAL FORMULA REVIEW URL
# ============================================================

def build_global_formula_review_url(
    formula
):

    url = reverse(
        "practice_formula",
        kwargs={
            "formula_id":
                formula.id,
        }
    )

    return (
        f"{url}"
        f"?review_mode=global"
    )


# ============================================================
# PRACTICE FORMULA
# ============================================================

@login_required
def practice_formula(
    request,
    formula_id
):
    """
    Formula recall practice.

    Supports two modes:

        normal
            Subject-specific scheduled review.

        global
            Review -> Formulas.
            Allows the student to move through formulas
            across all subjects.
    """

    # ========================================================
    # GET CURRENT FORMULA
    # ========================================================

    formula = get_object_or_404(
        Formula,
        id=formula_id,
        knowledge_unit__subject__user=request.user
    )

    knowledge_unit = (
        formula.knowledge_unit
    )

    # ========================================================
    # REVIEW MODE
    # ========================================================

    review_mode = (
        request.POST.get(
            "review_mode"
        )
        or request.GET.get(
            "review_mode"
        )
        or "normal"
    )

    if review_mode not in (
        "normal",
        "global",
    ):

        review_mode = "normal"

    # ========================================================
    # GET OR CREATE STUDENT PROGRESS
    # ========================================================

    progress, created = (
        StudentKnowledge.objects
        .get_or_create(
            student=request.user,
            knowledge_unit=knowledge_unit,
        )
    )

    # ========================================================
    # LOAD FORMULA STRUCTURE
    # ========================================================

    try:

        formula_elements = (
            json.loads(
                formula.structure
            )
        )

    except (
        json.JSONDecodeError,
        TypeError
    ):

        formula_elements = []

    all_elements = (
        get_all_elements(
            formula_elements
        )
    )

    # ========================================================
    # GLOBAL REVIEW -> NEXT FORMULA
    # ========================================================

    if (
        request.method == "POST"
        and
        request.POST.get(
            "action"
        ) == "next_formula"
    ):

        next_formula = (
            get_next_global_formula(
                request.user,
                formula,
            )
        )

        # ----------------------------------------------------
        # NEXT GLOBAL FORMULA
        # ----------------------------------------------------

        if next_formula is not None:

            return redirect(
                build_global_formula_review_url(
                    next_formula
                )
            )

        # ----------------------------------------------------
        # NO OTHER FORMULA EXISTS
        # ----------------------------------------------------

        return redirect(
            "review_formulas"
        )

    # ========================================================
    # SUBJECT REVIEW -> CONTINUE TO NEXT DUE FORMULA
    # ========================================================

    if (
        request.method == "POST"
        and
        request.POST.get(
            "action"
        ) == "continue"
    ):

        today = (
            timezone.localdate()
        )

        due_formulas = []

        # ----------------------------------------------------
        # GET ACTIVE FORMULAS FOR THIS SUBJECT ONLY
        # ----------------------------------------------------

        formulas = (
            Formula.objects
            .filter(
                knowledge_unit__subject=(
                    knowledge_unit.subject
                ),

                knowledge_unit__active=True,
            )
            .select_related(
                "knowledge_unit"
            )
            .order_by(
                "id"
            )
        )

        # ----------------------------------------------------
        # FIND ANOTHER DUE FORMULA
        # ----------------------------------------------------

        for next_formula in formulas:

            # Do not immediately show the formula
            # that was just reviewed.

            if (
                next_formula.id
                == formula.id
            ):

                continue

            next_knowledge_unit = (
                next_formula
                .knowledge_unit
            )

            # ------------------------------------------------
            # GET STUDENT PROGRESS
            # ------------------------------------------------

            next_progress = (
                StudentKnowledge.objects
                .filter(
                    student=request.user,

                    knowledge_unit=(
                        next_knowledge_unit
                    ),
                )
                .first()
            )

            # ------------------------------------------------
            # NEVER REVIEWED
            # ------------------------------------------------

            if next_progress is None:

                due_formulas.append(
                    next_formula
                )

                continue

            # ------------------------------------------------
            # CREATED BUT NEVER REVIEWED
            # ------------------------------------------------

            if (
                next_progress.review_count
                == 0
            ):

                due_formulas.append(
                    next_formula
                )

                continue

            # ------------------------------------------------
            # PREVIOUSLY REVIEWED AND DUE
            # ------------------------------------------------

            if (
                next_progress.next_review
                is not None
                and
                next_progress.next_review.date()
                <= today
            ):

                due_formulas.append(
                    next_formula
                )

        # ====================================================
        # ANOTHER FORMULA IS DUE
        # ====================================================

        if due_formulas:

            next_formula = (
                due_formulas[0]
            )

            return redirect(
                "practice_formula",
                formula_id=(
                    next_formula.id
                )
            )

        # ====================================================
        # NO MORE FORMULAS ARE DUE
        #
        # Return to the subject page.
        # ====================================================

        return redirect(
            "subject_detail",
            subject_index=(
                request.POST.get(
                    "subject_index",
                    0
                )
            )
        )

    # ========================================================
    # SUBMIT ANSWER
    # ========================================================

    if request.method == "POST":

        hidden_ids = (
            request.POST.getlist(
                "hidden_element_id"
            )
        )

        correct_answers = {}

        user_answers = {}

        all_correct = True

        # ====================================================
        # CHECK EVERY HIDDEN ELEMENT
        # ====================================================

        for hidden_id in hidden_ids:

            element = find_element(
                formula_elements,
                hidden_id
            )

            if not element:

                continue

            element_id = str(
                element.get(
                    "id"
                )
            )

            # ------------------------------------------------
            # STUDENT ANSWER
            # ------------------------------------------------

            user_answer = (
                request.POST.get(
                    "answer_"
                    + element_id,
                    ""
                )
                .strip()
            )

            # ------------------------------------------------
            # CORRECT ANSWER
            # ------------------------------------------------

            correct_answer = str(
                element.get(
                    "value",
                    ""
                )
            ).strip()

            # ------------------------------------------------
            # CHECK ANSWER
            # ------------------------------------------------

            is_correct = (
                user_answer
                == correct_answer
            )

            user_answers[
                element_id
            ] = user_answer

            correct_answers[
                element_id
            ] = correct_answer

            # ------------------------------------------------
            # RECORD ELEMENT PERFORMANCE
            # ------------------------------------------------

            record_element_performance(
                formula,
                element,
                is_correct
            )

            if not is_correct:

                all_correct = False

        # ====================================================
        # CORRECT
        # ====================================================

        if (
            all_correct
            and correct_answers
        ):

            progress.correct_count += 1

            progress.review_count += 1

            if (
                progress.mastery_level
                < 6
            ):

                progress.mastery_level += 1

            progress.last_reviewed = (
                timezone.now()
            )

            # ------------------------------------------------
            # CALCULATE NEXT REVIEW
            # ------------------------------------------------

            interval = (
                get_formula_review_interval(
                    progress.mastery_level
                )
            )

            progress.next_review = (
                timezone.now()
                + timedelta(
                    days=interval
                )
            )

            progress.save()

            result = "correct"

        # ====================================================
        # INCORRECT
        # ====================================================

        else:

            progress.incorrect_count += 1

            progress.review_count += 1

            if (
                progress.mastery_level
                > 0
            ):

                progress.mastery_level -= 1

            progress.last_reviewed = (
                timezone.now()
            )

            # ------------------------------------------------
            # INCORRECT ANSWERS RETURN TOMORROW
            # ------------------------------------------------

            progress.next_review = (
                timezone.now()
                + timedelta(
                    days=1
                )
            )

            progress.save()

            result = "incorrect"

        # ====================================================
        # BUILD RESULT ELEMENTS
        # ====================================================

        hidden_elements = []

        for element_id in correct_answers:

            element = find_element(
                formula_elements,
                element_id
            )

            if element:

                hidden_elements.append(
                    element
                )

        hidden_ids = [
            str(
                element.get(
                    "id"
                )
            )

            for element
            in hidden_elements
        ]

        # ====================================================
        # GLOBAL REVIEW -> FIND NEXT FORMULA
        # ====================================================

        next_formula = None

        if review_mode == "global":

            next_formula = (
                get_next_global_formula(
                    request.user,
                    formula,
                )
            )

        # ====================================================
        # SHOW RESULT
        # ====================================================

        return render(
            request,
            "practice/practice_formula.html",
            {
                "formula":
                    formula,

                "formula_elements":
                    formula_elements,

                "hidden_elements":
                    hidden_elements,

                "hidden_ids":
                    hidden_ids,

                "progress":
                    progress,

                "result":
                    result,

                "correct_answers":
                    correct_answers,

                "user_answers":
                    user_answers,

                "review_mode":
                    review_mode,

                "next_formula":
                    next_formula,
            }
        )

    # ========================================================
    # FIRST QUESTION
    # ========================================================

    hidden_elements = (
        choose_hidden_elements(
            all_elements,
            progress.mastery_level,
            formula,
        )
    )

    hidden_ids = [
        str(
            element.get(
                "id"
            )
        )

        for element
        in hidden_elements
    ]

    # ========================================================
    # RENDER QUESTION
    # ========================================================

    return render(
        request,
        "practice/practice_formula.html",
        {
            "formula":
                formula,

            "formula_elements":
                formula_elements,

            "hidden_elements":
                hidden_elements,

            "hidden_ids":
                hidden_ids,

            "progress":
                progress,

            "result":
                None,

            "correct_answers":
                {},

            "user_answers":
                {},

            "review_mode":
                review_mode,

            "next_formula":
                None,
        }
    )


# ============================================================
# RECONSTRUCTION ELEMENTS
# ============================================================

def get_reconstruction_elements(
    elements
):
    """
    Flatten the formula into reconstructable pieces.

    Fraction containers are kept as structural elements,
    while their numerator and denominator pieces are also
    included individually.
    """

    result = []

    for element in elements:

        if (
            element.get(
                "type"
            )
            == "fraction"
        ):

            result.append(
                element
            )

            result.extend(
                element.get(
                    "numerator",
                    []
                )
            )

            result.extend(
                element.get(
                    "denominator",
                    []
                )
            )

        else:

            result.append(
                element
            )

    return result


# ============================================================
# RECONSTRUCTION PERCENTAGE
# ============================================================

def get_reconstruction_percentage(
    mastery_level
):
    """
    Determines how much of the formula must be
    reconstructed.
    """

    percentages = {
        0: 15,
        1: 15,
        2: 30,
        3: 45,
        4: 60,
        5: 80,
        6: 100,
    }

    return percentages.get(
        mastery_level,
        15
    )


# ============================================================
# CHOOSE RECONSTRUCTION ELEMENTS
# ============================================================

def choose_reconstruction_elements(
    elements,
    mastery_level
):
    """
    Randomly selects the elements that the
    student must reconstruct.
    """

    if not elements:

        return []

    percentage = (
        get_reconstruction_percentage(
            mastery_level
        )
    )

    number_to_reconstruct = round(
        len(elements)
        * percentage
        / 100
    )

    number_to_reconstruct = max(
        1,
        number_to_reconstruct
    )

    number_to_reconstruct = min(
        number_to_reconstruct,
        len(elements)
    )

    return random.sample(
        elements,
        number_to_reconstruct
    )


# ============================================================
# FORMULA RECONSTRUCTION
# ============================================================

@login_required
def formula_reconstruction(
    request,
    formula_id
):
    """
    Formula reconstruction practice.

    The student reconstructs selected parts of
    the formula and then reports whether the
    reconstruction was correct.
    """

    # ========================================================
    # GET FORMULA
    # ========================================================

    formula = get_object_or_404(
        Formula,
        id=formula_id,
        knowledge_unit__subject__user=request.user
    )

    knowledge_unit = (
        formula.knowledge_unit
    )

    # ========================================================
    # GET OR CREATE PROGRESS
    # ========================================================

    progress, created = (
        StudentKnowledge.objects
        .get_or_create(
            student=request.user,
            knowledge_unit=knowledge_unit,
        )
    )

    # ========================================================
    # LOAD FORMULA
    # ========================================================

    try:

        formula_elements = (
            json.loads(
                formula.structure
            )
        )

    except (
        json.JSONDecodeError,
        TypeError
    ):

        formula_elements = []

    # ========================================================
    # GET RECONSTRUCTION ELEMENTS
    # ========================================================

    reconstruction_elements = (
        get_reconstruction_elements(
            formula_elements
        )
    )

    # ========================================================
    # CHOOSE HIDDEN ELEMENTS
    # ========================================================

    hidden_reconstruction_elements = (
        choose_reconstruction_elements(
            reconstruction_elements,
            progress.mastery_level
        )
    )

    hidden_reconstruction_ids = [
        str(
            element.get(
                "id"
            )
        )

        for element
        in hidden_reconstruction_elements
    ]

    result = None

    # ========================================================
    # SUBMIT REVIEW RESULT
    # ========================================================

    if request.method == "POST":

        result = (
            request.POST.get(
                "result"
            )
        )

        # ====================================================
        # CORRECT
        # ====================================================

        if result == "correct":

            progress.review_count += 1

            progress.correct_count += 1

            if (
                progress.mastery_level
                < 6
            ):

                progress.mastery_level += 1

            progress.last_reviewed = (
                timezone.now()
            )

            progress.next_review = (
                timezone.now()
            )

            progress.save()

            return redirect(
                "formula_reconstruction",
                formula_id=formula.id
            )

        # ====================================================
        # INCORRECT
        # ====================================================

        elif result == "incorrect":

            progress.review_count += 1

            progress.incorrect_count += 1

            if (
                progress.mastery_level
                > 0
            ):

                progress.mastery_level -= 1

            progress.last_reviewed = (
                timezone.now()
            )

            progress.next_review = (
                timezone.now()
            )

            progress.save()

            return render(
                request,
                "practice/formula_reconstructions.html",
                {
                    "formula":
                        formula,

                    "formula_elements":
                        formula_elements,

                    "reconstruction_elements":
                        reconstruction_elements,

                    "hidden_reconstruction_elements":
                        hidden_reconstruction_elements,

                    "hidden_reconstruction_ids":
                        hidden_reconstruction_ids,

                    "progress":
                        progress,

                    "result":
                        "incorrect",
                }
            )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "practice/formula_reconstructions.html",
        {
            "formula":
                formula,

            "formula_elements":
                formula_elements,

            "reconstruction_elements":
                reconstruction_elements,

            "hidden_reconstruction_elements":
                hidden_reconstruction_elements,

            "hidden_reconstruction_ids":
                hidden_reconstruction_ids,

            "progress":
                progress,

            "result":
                result,
        }
    )


# ============================================================
# ADD FORMULA — LEGACY / ONBOARDING
# ============================================================

@login_required
def add_formula(
    request,
    subject_index
):
    """
    Legacy formula creation used by the onboarding/practice
    flow.

    The newer database-backed formula creation lives in
    learning.views.create_formula.
    """

    profile = (
        request.session.get(
            "onboarding_profile"
        )
    )

    if not profile:

        return redirect(
            "onboarding"
        )

    subjects = (
        request.session.get(
            "onboarding_subjects",
            []
        )
    )

    # ========================================================
    # VALIDATE SUBJECT INDEX
    # ========================================================

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
        or
        subject_index >= len(
            subjects
        )
    ):

        return redirect(
            "goals"
        )

    subject = (
        subjects[
            subject_index
        ]
    )

    # --------------------------------------------------------
    # MAKE SURE FORMULAS LIST EXISTS
    # --------------------------------------------------------

    if "formulas" not in subject:

        subject[
            "formulas"
        ] = []

    # ========================================================
    # CREATE FORMULA
    # ========================================================

    if request.method == "POST":

        name = (
            request.POST.get(
                "name",
                ""
            )
            .strip()
        )

        formula = (
            request.POST.get(
                "formula",
                ""
            )
            .strip()
        )

        description = (
            request.POST.get(
                "description",
                ""
            )
            .strip()
        )

        if (
            name
            and formula
        ):

            subject[
                "formulas"
            ].append(
                {
                    "name":
                        name,

                    "formula":
                        formula,

                    "description":
                        description,
                }
            )

            subjects[
                subject_index
            ] = subject

            request.session[
                "onboarding_subjects"
            ] = subjects

            request.session.modified = (
                True
            )

            return redirect(
                "add_formula",
                subject_index=subject_index
            )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "practice/formulas.html",
        {
            "subject":
                subject,

            "subject_index":
                subject_index,

            "formulas":
                subject[
                    "formulas"
                ],
        }
    )
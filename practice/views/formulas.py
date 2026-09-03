from datetime import timedelta
from urllib.parse import urlencode

import json
import random

from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    render,
    redirect,
    get_object_or_404,
)
from django.urls import reverse
from django.utils import timezone

from learning.models import (
    Formula,
    StudentKnowledge,
    FormulaElementPerformance,
)


# ============================================================
# GET ALL FORMULA ELEMENTS
# ============================================================

def get_all_elements(
    elements
):
    """
    Recursively collect every testable element in the formula,
    including elements inside fractions.

    The "=" operator is excluded because we do not want
    students tested on the equals sign.
    """

    result = []

    for element in elements:

        element_type = (
            element.get(
                "type"
            )
        )

        value = str(
            element.get(
                "value",
                ""
            )
        ).strip()

        # ----------------------------------------------------
        # DO NOT TEST =
        # ----------------------------------------------------

        if (
            element_type == "operator"
            and
            value == "="
        ):

            continue

        # ----------------------------------------------------
        # FRACTION
        # ----------------------------------------------------

        if (
            element_type
            ==
            "fraction"
        ):

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

        # ----------------------------------------------------
        # NORMAL ELEMENT
        # ----------------------------------------------------

        else:

            result.append(
                element
            )

    return result


# ============================================================
# FIND FORMULA ELEMENT
# ============================================================

def find_element(
    elements,
    element_id
):
    """
    Find one formula element by its ID.

    Works recursively inside fractions.
    """

    for element in elements:

        if (
            str(
                element.get(
                    "id"
                )
            )
            ==
            str(
                element_id
            )
        ):

            return element

        if (
            element.get(
                "type"
            )
            ==
            "fraction"
        ):

            # ------------------------------------------------
            # NUMERATOR
            # ------------------------------------------------

            found = (
                find_element(
                    element.get(
                        "numerator",
                        []
                    ),
                    element_id
                )
            )

            if found:

                return found

            # ------------------------------------------------
            # DENOMINATOR
            # ------------------------------------------------

            found = (
                find_element(
                    element.get(
                        "denominator",
                        []
                    ),
                    element_id
                )
            )

            if found:

                return found

    return None


# ============================================================
# GET DESCRIPTION MATCH ITEMS
# ============================================================

def get_description_match_items(
    elements
):
    """
    Find every variable or symbol that has a saved
    meaning / description.

    These become the targets in the second-stage
    mastered-formula test.

    Works recursively inside fractions.
    """

    result = []

    for element in elements:

        element_type = (
            element.get(
                "type",
                ""
            )
        )

        # ----------------------------------------------------
        # FRACTION
        # ----------------------------------------------------

        if (
            element_type
            ==
            "fraction"
        ):

            result.extend(
                get_description_match_items(
                    element.get(
                        "numerator",
                        []
                    )
                )
            )

            result.extend(
                get_description_match_items(
                    element.get(
                        "denominator",
                        []
                    )
                )
            )

            continue

        # ----------------------------------------------------
        # ONLY VARIABLE + SYMBOL
        # ----------------------------------------------------

        if (
            element_type
            not in (
                "variable",
                "symbol",
            )
        ):

            continue

        element_id = str(
            element.get(
                "id",
                ""
            )
        ).strip()

        value = str(
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

        # ----------------------------------------------------
        # MUST HAVE DESCRIPTION
        # ----------------------------------------------------

        if (
            not element_id
            or
            not value
            or
            not meaning
        ):

            continue

        result.append(
            {
                "id":
                    element_id,

                "type":
                    element_type,

                "value":
                    value,

                "meaning":
                    meaning,
            }
        )

    return result


# ============================================================
# REVIEW INTERVAL
# ============================================================

def get_formula_review_interval(
    mastery_level
):
    """
    Number of days until the next formula review.
    """

    intervals = {

        0:
            0,

        1:
            1,

        2:
            2,

        3:
            4,

        4:
            7,

        5:
            14,

        6:
            30,

    }

    return intervals.get(
        mastery_level,
        0
    )


# ============================================================
# MASTERY -> HIDDEN PERCENTAGE
# ============================================================

def get_hidden_percentage(
    mastery_level
):
    """
    Determine how much of the formula should be hidden.

    At mastery 6 the complete testable formula is hidden.
    """

    percentages = {

        0:
            10,

        1:
            15,

        2:
            30,

        3:
            45,

        4:
            60,

        5:
            80,

        6:
            100,

    }

    return percentages.get(
        mastery_level,
        15
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
    Record performance for one individual formula element.

    This is only for the normal formula test.

    Description matching does NOT call this function.
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
    # KEEP CURRENT ELEMENT DETAILS
    # --------------------------------------------------------

    performance.element_type = (
        element_type
    )

    performance.value = (
        value
    )

    performance.last_reviewed = (
        timezone.now()
    )

    # --------------------------------------------------------
    # CORRECT / INCORRECT
    # --------------------------------------------------------

    if is_correct:

        performance.correct_count += (
            1
        )

    else:

        performance.incorrect_count += (
            1
        )

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

    Weak elements receive priority.

    Approximately:

        70% weaker elements
        30% random elements

    At mastery level 6 every testable element is hidden.
    """

    if not all_elements:

        return []

    percentage = (
        get_hidden_percentage(
            mastery_level
        )
    )

    # ========================================================
    # MASTERY 6 = EVERYTHING
    # ========================================================

    if (
        percentage
        >=
        100
    ):

        return (
            all_elements.copy()
        )

    # ========================================================
    # NUMBER TO HIDE
    # ========================================================

    number_to_hide = round(
        len(
            all_elements
        )
        *
        percentage
        /
        100
    )

    # --------------------------------------------------------
    # ALWAYS AT LEAST ONE
    # --------------------------------------------------------

    number_to_hide = max(
        1,
        number_to_hide
    )

    number_to_hide = min(
        number_to_hide,
        len(
            all_elements
        )
    )

    previous_ids = (
        previous_ids
        or
        []
    )

    # ========================================================
    # PERFORMANCE DATA
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
    # WEAKNESS
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

            weakness = (
                1.0
            )

        else:

            total = (
                record.correct_count
                +
                record.incorrect_count
            )

            if total == 0:

                weakness = (
                    1.0
                )

            else:

                accuracy = (
                    record.correct_count
                    /
                    total
                )

                weakness = (
                    1
                    -
                    accuracy
                )

        weighted_elements.append(
            (
                element,
                weakness
            )
        )

    # ========================================================
    # AVOID SAME ELEMENTS IMMEDIATELY
    # ========================================================

    available = [

        item

        for item
        in weighted_elements

        if str(
            item[0].get(
                "id"
            )
        )
        not in previous_ids

    ]

    if (
        len(
            available
        )
        <
        number_to_hide
    ):

        available = (
            weighted_elements
        )

    # ========================================================
    # WEAK / RANDOM SPLIT
    # ========================================================

    weak_count = round(
        number_to_hide
        *
        0.7
    )

    weak_count = min(
        weak_count,
        number_to_hide
    )

    random_count = (
        number_to_hide
        -
        weak_count
    )

    sorted_elements = sorted(
        available,

        key=lambda item:
            item[1],

        reverse=True
    )

    weak_candidates = [

        element

        for (
            element,
            weakness
        )
        in sorted_elements

        if weakness > 0

    ]

    selected = []

    # ========================================================
    # WEAK ELEMENTS
    # ========================================================

    if weak_candidates:

        weak_pool_size = max(

            weak_count,

            min(
                len(
                    weak_candidates
                ),
                max(
                    1,
                    weak_count * 2
                )
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
    # RANDOM ELEMENTS
    # ========================================================

    remaining = [

        element

        for (
            element,
            weakness
        )
        in available

        if element
        not in selected

    ]

    if (
        remaining
        and
        random_count > 0
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
    # FILL ANY REMAINING SLOTS
    # ========================================================

    if (
        len(
            selected
        )
        <
        number_to_hide
    ):

        remaining = [

            element

            for (
                element,
                weakness
            )
            in available

            if element
            not in selected

        ]

        if remaining:

            selected.extend(
                random.sample(
                    remaining,

                    min(
                        number_to_hide
                        -
                        len(
                            selected
                        ),

                        len(
                            remaining
                        )
                    )
                )
            )

    return (
        selected[
            :number_to_hide
        ]
    )


# ============================================================
# FIND SUBJECT INDEX
# ============================================================

def get_formula_subject_index(
    request,
    subject
):
    """
    Find the subject's onboarding-session index.
    """

    supplied_index = (
        request.POST.get(
            "subject_index"
        )
        or
        request.GET.get(
            "subject_index"
        )
    )

    if (
        supplied_index
        is not None
    ):

        try:

            return int(
                supplied_index
            )

        except (
            TypeError,
            ValueError
        ):

            pass

    subjects = (
        request.session.get(
            "onboarding_subjects",
            []
        )
    )

    # --------------------------------------------------------
    # DATABASE ID
    # --------------------------------------------------------

    for (
        index,
        subject_data
    ) in enumerate(
        subjects
    ):

        database_id = (
            subject_data.get(
                "database_id"
            )
        )

        try:

            database_id = int(
                database_id
            )

        except (
            TypeError,
            ValueError
        ):

            database_id = (
                None
            )

        if (
            database_id
            ==
            subject.id
        ):

            return index

    # --------------------------------------------------------
    # NAME FALLBACK
    # --------------------------------------------------------

    for (
        index,
        subject_data
    ) in enumerate(
        subjects
    ):

        if (
            subject_data.get(
                "name",
                ""
            ).strip()
            ==
            subject.name.strip()
        ):

            return index

    return 0


# ============================================================
# FIND NEXT DUE FORMULA
# ============================================================

def get_next_due_formula(
    user,
    current_formula,
    subject=None
):
    """
    Find the next due formula.

    subject=None:
        search all subjects.

    subject=<subject>:
        search only the current subject.
    """

    formulas = (
        Formula.objects
        .filter(
            knowledge_unit__subject__user=user,

            knowledge_unit__active=True,
        )
        .exclude(
            id=current_formula.id
        )
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        )
        .order_by(
            "knowledge_unit__subject__name",
            "knowledge_unit__title",
            "id",
        )
    )

    if (
        subject
        is not None
    ):

        formulas = (
            formulas.filter(
                knowledge_unit__subject=subject
            )
        )

    now = (
        timezone.now()
    )

    for formula in formulas:

        progress = (
            StudentKnowledge.objects
            .filter(
                student=user,

                knowledge_unit=(
                    formula.knowledge_unit
                ),
            )
            .first()
        )

        # ----------------------------------------------------
        # NEVER REVIEWED
        # ----------------------------------------------------

        if progress is None:

            return formula

        # ----------------------------------------------------
        # NO DATE = DUE
        # ----------------------------------------------------

        if (
            progress.next_review
            is None
        ):

            return formula

        # ----------------------------------------------------
        # REVIEW DUE
        # ----------------------------------------------------

        if (
            progress.next_review
            <=
            now
        ):

            return formula

    return None


# ============================================================
# BUILD PRACTICE URL
# ============================================================

def build_formula_practice_url(
    formula,
    review_mode,
    subject_index
):
    """
    Build the next formula URL while preserving review mode.
    """

    url = reverse(
        "practice_formula",
        args=[
            formula.id
        ]
    )

    parameters = {
        "review_mode":
            review_mode,

        "subject_index":
            subject_index,
    }

    return (
        url
        +
        "?"
        +
        urlencode(
            parameters
        )
    )


# ============================================================
# PRACTICE FORMULA
# ============================================================

@login_required
def practice_formula(
    request,
    formula_id
):

    # ========================================================
    # FORMULA
    # ========================================================

    formula = get_object_or_404(
        Formula.objects.select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        ),

        id=formula_id,

        knowledge_unit__subject__user=(
            request.user
        ),
    )

    knowledge_unit = (
        formula.knowledge_unit
    )

    subject = (
        knowledge_unit.subject
    )

    # ========================================================
    # PROGRESS
    # ========================================================

    progress, created = (
        StudentKnowledge.objects
        .get_or_create(
            student=request.user,

            knowledge_unit=(
                knowledge_unit
            ),
        )
    )

    # ========================================================
    # REVIEW MODE
    # ========================================================

    review_mode = (
        request.POST.get(
            "review_mode"
        )
        or
        request.GET.get(
            "review_mode"
        )
        or
        "normal"
    )

    # Support old/global links too.
    if (
        request.GET.get(
            "all_subjects"
        )
        ==
        "1"
    ):

        review_mode = (
            "global"
        )

    if (
        review_mode
        not in (
            "normal",
            "global",
        )
    ):

        review_mode = (
            "normal"
        )

    # ========================================================
    # SUBJECT INDEX
    # ========================================================

    subject_index = (
        get_formula_subject_index(
            request,
            subject
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

        if not isinstance(
            formula_elements,
            list
        ):

            formula_elements = []

    except (
        json.JSONDecodeError,
        TypeError
    ):

        formula_elements = []

    # ========================================================
    # TESTABLE ELEMENTS
    # ========================================================

    all_elements = (
        get_all_elements(
            formula_elements
        )
    )

    # ========================================================
    # DESCRIPTION MATCHING DATA
    # ========================================================

    description_match_items = (
        get_description_match_items(
            formula_elements
        )
    )

    description_match_cards = [

        item.copy()

        for item
        in description_match_items

    ]

    random.shuffle(
        description_match_cards
    )

    # ========================================================
    # ACTION BUTTONS AFTER RESULT
    # ========================================================

    if (
        request.method
        ==
        "POST"
    ):

        action = (
            request.POST.get(
                "action",
                ""
            )
        )

        # ----------------------------------------------------
        # NEXT FORMULA — GLOBAL
        # ----------------------------------------------------

        if (
            action
            ==
            "next_formula"
        ):

            next_formula = (
                get_next_due_formula(
                    request.user,
                    formula,
                    subject=None
                )
            )

            if next_formula:

                return redirect(
                    build_formula_practice_url(
                        next_formula,
                        "global",
                        subject_index
                    )
                )

            return redirect(
                "review_formulas"
            )

        # ----------------------------------------------------
        # CONTINUE — CURRENT SUBJECT
        # ----------------------------------------------------

        if (
            action
            ==
            "continue"
        ):

            next_formula = (
                get_next_due_formula(
                    request.user,
                    formula,
                    subject=subject
                )
            )

            if next_formula:

                return redirect(
                    build_formula_practice_url(
                        next_formula,
                        "normal",
                        subject_index
                    )
                )

            return redirect(
                "formula_review_list",
                subject_index=subject_index
            )

    # ========================================================
    # PAGE STATE
    # ========================================================

    hidden_elements = []

    hidden_ids = []

    result = None

    correct_answers = {}

    user_answers = {}

    next_formula = None

    show_description_match = (
        False
    )

    # ========================================================
    # SUBMIT NORMAL FORMULA ANSWER
    # ========================================================

    if (
        request.method
        ==
        "POST"
    ):

        # ====================================================
        # IMPORTANT:
        #
        # Remember mastery BEFORE marking the formula.
        #
        # If student was 5/6 and this answer makes them 6/6,
        # the matching stage must NOT appear yet.
        #
        # It only appears on a future review that STARTED 6/6.
        # ====================================================

        was_already_mastered = (
            progress.mastery_level
            >=
            6
        )

        hidden_ids = (
            request.POST.getlist(
                "hidden_element_id"
            )
        )

        # ====================================================
        # CHECK EVERY HIDDEN ELEMENT
        # ====================================================

        for hidden_id in hidden_ids:

            element = (
                find_element(
                    formula_elements,
                    hidden_id
                )
            )

            if not element:

                continue

            element_id = str(
                element.get(
                    "id"
                )
            )

            user_answer = (
                request.POST.get(
                    "answer_"
                    +
                    element_id,
                    ""
                )
                .strip()
            )

            correct_answer = str(
                element.get(
                    "value",
                    ""
                )
            ).strip()

            is_correct = (
                user_answer
                ==
                correct_answer
            )

            user_answers[
                element_id
            ] = (
                user_answer
            )

            correct_answers[
                element_id
            ] = (
                correct_answer
            )

            # ------------------------------------------------
            # NORMAL FORMULA ELEMENT PERFORMANCE
            # ------------------------------------------------

            record_element_performance(
                formula,
                element,
                is_correct
            )

        # ====================================================
        # DID THEY GET EVERYTHING CORRECT?
        # ====================================================

        all_correct = bool(
            correct_answers
        )

        if all_correct:

            for (
                element_id,
                correct_answer
            ) in correct_answers.items():

                if (
                    user_answers.get(
                        element_id,
                        ""
                    )
                    !=
                    correct_answer
                ):

                    all_correct = (
                        False
                    )

                    break

        # ====================================================
        # CORRECT FORMULA
        # ====================================================

        if all_correct:

            progress.correct_count += (
                1
            )

            if (
                progress.mastery_level
                <
                6
            ):

                progress.mastery_level += (
                    1
                )

            progress.review_count += (
                1
            )

            progress.last_reviewed = (
                timezone.now()
            )

            interval = (
                get_formula_review_interval(
                    progress.mastery_level
                )
            )

            progress.next_review = (
                timezone.now()
                +
                timedelta(
                    days=interval
                )
            )

            progress.save()

            result = (
                "correct"
            )

            # =================================================
            # MASTERED SECOND STAGE
            #
            # Only if:
            #
            # 1. Formula STARTED this review at 6/6
            # 2. Normal formula was correct
            # 3. At least one variable/symbol has description
            # =================================================

            show_description_match = (

                was_already_mastered

                and

                bool(
                    description_match_items
                )

            )

        # ====================================================
        # INCORRECT FORMULA
        # ====================================================

        else:

            progress.incorrect_count += (
                1
            )

            if (
                progress.mastery_level
                >
                0
            ):

                progress.mastery_level -= (
                    1
                )

            progress.review_count += (
                1
            )

            progress.last_reviewed = (
                timezone.now()
            )

            interval = (
                get_formula_review_interval(
                    progress.mastery_level
                )
            )

            progress.next_review = (
                timezone.now()
                +
                timedelta(
                    days=interval
                )
            )

            progress.save()

            result = (
                "incorrect"
            )

            # ------------------------------------------------
            # DESCRIPTION TEST NEVER APPEARS IF NORMAL
            # FORMULA WAS WRONG.
            # ------------------------------------------------

            show_description_match = (
                False
            )

        # ====================================================
        # KEEP CURRENT TESTED ELEMENTS
        # ====================================================

        hidden_elements = []

        for element_id in hidden_ids:

            element = (
                find_element(
                    formula_elements,
                    element_id
                )
            )

            if element:

                hidden_elements.append(
                    element
                )

    # ========================================================
    # FIRST DISPLAY OF QUESTION
    # ========================================================

    else:

        hidden_elements = (
            choose_hidden_elements(
                all_elements,
                progress.mastery_level,
                formula
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
    # NEXT DUE FORMULA
    #
    # Only needed for the result screen.
    # ========================================================

    if (
        result
        is not None
    ):

        if (
            review_mode
            ==
            "global"
        ):

            next_formula = (
                get_next_due_formula(
                    request.user,
                    formula,
                    subject=None
                )
            )

        else:

            next_formula = (
                get_next_due_formula(
                    request.user,
                    formula,
                    subject=subject
                )
            )

    # ========================================================
    # RENDER
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
                result,

            "correct_answers":
                correct_answers,

            "user_answers":
                user_answers,

            "review_mode":
                review_mode,

            "subject_index":
                subject_index,

            "next_formula":
                next_formula,

            # ================================================
            # MASTERED DESCRIPTION TEST
            # ================================================

            "description_match_items":
                description_match_items,

            "description_match_cards":
                description_match_cards,

            "show_description_match":
                show_description_match,
        }
    )

# ============================================================
# FORMULA RECONSTRUCTION
# ============================================================
#
# Compatibility view.
#
# Older URLs / imports still reference
# "formula_reconstruction".
#
# The new practice_formula view now handles full formula
# reconstruction automatically at mastery 6, so old
# reconstruction links are redirected there.
# ============================================================

@login_required
def formula_reconstruction(
    request,
    formula_id
):

    formula = get_object_or_404(
        Formula,
        id=formula_id,
        knowledge_unit__subject__user=request.user,
    )

    return redirect(
        "practice_formula",
        formula_id=formula.id,
    )
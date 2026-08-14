from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

import json
import random

from learning.models import (
    Formula,
    StudentKnowledge,
    FormulaElementPerformance,
)


# ============================================================
# GET ALL FORMULA ELEMENTS
# ============================================================

def get_all_elements(elements):
    """
    Recursively collect every testable element
    in the formula, including elements inside
    fractions.

    The "=" operator is excluded because we
    do not want students tested on it.
    """

    result = []

    for element in elements:

        element_type = element.get("type")
        value = str(
            element.get("value", "")
        ).strip()

        # Do not test the "=" sign.
        if (
            element_type == "operator"
            and value == "="
        ):
            continue

        # Fractions contain their own elements.
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

            result.append(element)

    return result


# ============================================================
# FIND AN ELEMENT BY UUID
# ============================================================

def find_element(elements, element_id):

    for element in elements:

        if str(
            element.get("id")
        ) == str(element_id):

            return element


        if element.get("type") == "fraction":

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
# RECORD ELEMENT PERFORMANCE
# ============================================================

def record_element_performance(
    formula,
    element,
    is_correct
):
    """
    Record whether the student got
    one specific formula element correct
    or incorrect.
    """

    element_id = str(
        element.get(
            "id",
            ""
        )
    )

    if not element_id:
        return


    element_type = element.get(
        "type",
        ""
    )

    value = str(
        element.get(
            "value",
            ""
        )
    )


    performance, created = (
        FormulaElementPerformance.objects.get_or_create(

            formula=formula,

            element_id=element_id,

            defaults={
                "element_type": element_type,
                "value": value,
            }

        )
    )


    # Keep the stored element information
    # synchronized with the formula.
    performance.element_type = (
        element_type
    )

    performance.value = value

    performance.last_reviewed = (
        timezone.now()
    )


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
    Choose which elements should be hidden.

    Weak elements receive priority.

    Approximately:

        70% = weaker elements
        30% = random elements

    This keeps the exercise adaptive without
    becoming completely predictable.

    At mastery level 6, all testable elements
    are hidden.
    """

    if not all_elements:

        return []


    percentage = get_hidden_percentage(
        mastery_level
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


    previous_ids = previous_ids or []


    # ========================================================
    # GET PERFORMANCE DATA
    # ========================================================

    performance_records = (
        FormulaElementPerformance.objects.filter(
            formula=formula
        )
    )


    performance_map = {

        str(record.element_id): record

        for record
        in performance_records

    }


    # ========================================================
    # CALCULATE WEAKNESS
    # ========================================================

    weighted_elements = []


    for element in all_elements:

        element_id = str(
            element.get("id")
        )


        record = performance_map.get(
            element_id
        )


        # Never tested before.
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
                    1 - accuracy
                )


        weighted_elements.append(
            (
                element,
                weakness
            )
        )


    # ========================================================
    # AVOID IMMEDIATELY REPEATING SAME ELEMENTS
    # ========================================================

    available = [

        item

        for item in weighted_elements

        if str(
            item[0].get("id")
        ) not in previous_ids

    ]


    # If there aren't enough alternatives,
    # allow previous elements again.
    if len(available) < number_to_hide:

        available = weighted_elements


    # ========================================================
    # SPLIT SELECTION
    # ========================================================

    weak_count = round(
        number_to_hide * 0.7
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

    if weak_candidates:

        weak_pool_size = max(

            weak_count,

            min(
                len(weak_candidates),
                weak_count * 2
            )

        )


        weak_pool = weak_candidates[
            :weak_pool_size
        ]


        selected.extend(

            random.sample(

                weak_pool,

                min(
                    weak_count,
                    len(weak_pool)
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


    if remaining and random_count > 0:

        selected.extend(

            random.sample(

                remaining,

                min(
                    random_count,
                    len(remaining)
                )

            )

        )


    # ========================================================
    # FILL REMAINING SPACES
    # ========================================================

    if len(selected) < number_to_hide:

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
                        - len(selected),

                        len(remaining)

                    )

                )

            )


    return selected[
        :number_to_hide
    ]


# ============================================================
# PRACTICE FORMULA
# ============================================================

@login_required
def practice_formula(
    request,
    formula_id
):

    formula = get_object_or_404(

        Formula,

        id=formula_id,

        knowledge_unit__topic__subject__user=request.user

    )


    knowledge_unit = (
        formula.knowledge_unit
    )


    progress, created = (
        StudentKnowledge.objects.get_or_create(

            student=request.user,

            knowledge_unit=knowledge_unit,

        )
    )


    # ========================================================
    # LOAD FORMULA
    # ========================================================

    try:

        formula_elements = json.loads(
            formula.structure
        )

    except (
        json.JSONDecodeError,
        TypeError
    ):

        formula_elements = []


    all_elements = get_all_elements(
        formula_elements
    )


    hidden_elements = []

    result = None

    correct_answers = {}

    user_answers = {}


    # ========================================================
    # SUBMIT ANSWER
    # ========================================================

    if request.method == "POST":

        hidden_ids = request.POST.getlist(
            "hidden_element_id"
        )


        # ====================================================
        # CHECK EACH HIDDEN ELEMENT
        # ====================================================

        for hidden_id in hidden_ids:

            element = find_element(

                formula_elements,

                hidden_id

            )


            if not element:

                continue


            element_id = str(
                element.get("id")
            )


            user_answer = request.POST.get(

                "answer_" + element_id,

                ""

            ).strip()


            correct_answer = str(

                element.get(
                    "value",
                    ""
                )

            ).strip()


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


            # =================================================
            # RECORD ELEMENT PERFORMANCE
            # =================================================

            record_element_performance(

                formula,

                element,

                is_correct

            )


        # ====================================================
        # CHECK WHETHER EVERYTHING WAS CORRECT
        # ====================================================

        all_correct = True


        for element_id in correct_answers:

            if (

                user_answers.get(
                    element_id,
                    ""
                )

                !=

                correct_answers[
                    element_id
                ]

            ):

                all_correct = False

                break


        # ====================================================
        # CORRECT
        # ====================================================

        if (

            all_correct

            and correct_answers

        ):

            progress.correct_count += 1


            if progress.mastery_level < 6:

                progress.mastery_level += 1


            progress.review_count += 1


            progress.last_reviewed = (
                timezone.now()
            )


            progress.next_review = (
                timezone.now()
            )


            progress.save()


            previous_ids = list(
                correct_answers.keys()
            )


            # Immediately generate the
            # next question.
            hidden_elements = (
                choose_hidden_elements(

                    all_elements,

                    progress.mastery_level,

                    formula,

                    previous_ids

                )
            )


            result = "next"


        # ====================================================
        # INCORRECT
        # ====================================================

        else:

            progress.incorrect_count += 1


            if progress.mastery_level > 0:

                progress.mastery_level -= 1


            progress.review_count += 1


            progress.last_reviewed = (
                timezone.now()
            )


            progress.next_review = (
                timezone.now()
            )


            progress.save()


            # Keep the same elements visible
            # so the student can see the correct
            # answers.
            hidden_elements = [

                find_element(

                    formula_elements,

                    element_id

                )

                for element_id
                in correct_answers

            ]


            hidden_elements = [

                element

                for element
                in hidden_elements

                if element

            ]


            result = "incorrect"


    # ========================================================
    # FIRST QUESTION
    # ========================================================

    else:

        hidden_elements = (
            choose_hidden_elements(

                all_elements,

                progress.mastery_level,

                formula

            )
        )


    # ========================================================
    # HIDDEN UUIDS
    # ========================================================

    hidden_ids = [

        str(
            element.get("id")
        )

        for element
        in hidden_elements

    ]


    # ========================================================
    # RENDER
    # ========================================================

    return render(

        request,

        "practice/practice_formula.html",

        {

            "formula": formula,

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

        }

    )

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404

import json

from learning.models import Formula


def get_reconstruction_elements(elements):
    """
    Flatten the formula into individual reconstructable pieces.

    Fraction containers are kept as structural elements,
    while their numerator and denominator pieces are also
    included individually.
    """

    result = []

    for element in elements:

        if element.get("type") == "fraction":

            # The fraction container itself
            result.append(element)

            # Numerator pieces
            for part in element.get(
                "numerator",
                []
            ):
                result.append(part)

            # Denominator pieces
            for part in element.get(
                "denominator",
                []
            ):
                result.append(part)

        else:

            result.append(element)

    return result


def get_reconstruction_percentage(mastery_level):
    """
    Determines how much of the formula must be reconstructed.
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

    percentage = get_reconstruction_percentage(
        mastery_level
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

@login_required
def formula_reconstruction(request, formula_id):

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


    reconstruction_elements = (
        get_reconstruction_elements(
            formula_elements
        )
    )


    hidden_reconstruction_elements = (
        choose_reconstruction_elements(
            reconstruction_elements,
            progress.mastery_level
        )
    )

    hidden_reconstruction_ids = [
        str(element.get("id"))
        for element in hidden_reconstruction_elements
    ]


    result = None

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


    reconstruction_elements = (
        get_reconstruction_elements(
            formula_elements
        )
    )

    hidden_reconstruction_elements = (
    choose_reconstruction_elements(
        reconstruction_elements,
        progress.mastery_level
    )
)

    result = None


    # ==========================================
    # REVIEW RESULT
    # ==========================================

    if request.method == "POST":

        result = request.POST.get(
            "result"
        )


        # ======================================
        # CORRECT
        # ======================================

        if result == "correct":

            progress.review_count += 1
            progress.correct_count += 1

            if progress.mastery_level < 6:
                progress.mastery_level += 1

            progress.last_reviewed = timezone.now()
            progress.next_review = timezone.now()

            progress.save()

            return redirect(
                "formula_reconstruction",
                formula_id=formula.id
            )

        # ======================================
        # INCORRECT
        # ======================================

        elif result == "incorrect":

            progress.review_count += 1

            progress.incorrect_count += 1

            if progress.mastery_level > 0:
                progress.mastery_level -= 1

            progress.last_reviewed = timezone.now()
            progress.next_review = timezone.now()

            progress.save()

            return render(
                request,
                "practice/formula_reconstructions.html",
                {
                    "formula": formula,
                    "formula_elements": formula_elements,
                    "reconstruction_elements": reconstruction_elements,
                    "progress": progress,
                    "result": "incorrect",
                }
            )

    return render(
        request,
        "practice/formula_reconstructions.html",
        {
            "formula": formula,

            "formula_elements":
                formula_elements,

            "reconstruction_elements":
                reconstruction_elements,

            "progress":
                progress,

            "result":
                result,
        }
    )


    formula = get_object_or_404(
        Formula,
        id=formula_id,
        knowledge_unit__topic__subject__user=request.user
    )

    try:

        formula_elements = json.loads(
            formula.structure
        )

    except (json.JSONDecodeError, TypeError):

        formula_elements = []


    reconstruction_elements = (
        get_reconstruction_elements(
            formula_elements
        )
    )


    return render(
        request,
        "practice/formula_reconstructions.html",
        {
            "formula": formula,
            "formula_elements": formula_elements,
            "reconstruction_elements": (
                reconstruction_elements
            ),
        }
    )



    formula = get_object_or_404(
        Formula,
        id=formula_id,
        knowledge_unit__topic__subject__user=request.user
    )

    try:

        formula_elements = json.loads(
            formula.structure
        )

    except (json.JSONDecodeError, TypeError):

        formula_elements = []


    reconstruction_elements = (
        get_reconstruction_elements(
            formula_elements
        )
    )


    return render(
        request,
        "practice/formula_reconstructions.html",
        {
            "formula": formula,
            "formula_elements": formula_elements,
            "reconstruction_elements": (
                reconstruction_elements
            ),
            "hidden_reconstruction_elements":
            hidden_reconstruction_elements,

            "hidden_reconstruction_ids":
            hidden_reconstruction_ids,
        }
    )
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404

import json
import random

from django.utils import timezone

from learning.models import (
    Formula,
    StudentKnowledge,
    FormulaElementPerformance,
)


def get_all_elements(elements):
    """
    Recursively collect every testable element in the formula,
    including elements inside fractions.

    The "=" operator is deliberately excluded because
    it should never be tested.
    """

    result = []

    for element in elements:

        element_type = element.get("type")
        value = element.get("value", "")

        # ==================================================
        # FRACTION
        # ==================================================

        if element_type == "fraction":

            result.extend(
                get_all_elements(
                    element.get("numerator", [])
                )
            )

            result.extend(
                get_all_elements(
                    element.get("denominator", [])
                )
            )

        # ==================================================
        # EVERYTHING ELSE
        # ==================================================

        else:

            # Never test the "=" sign.
            if not (
                element_type == "operator"
                and value == "="
            ):

                result.append(element)

    return result


def find_element(elements, element_id):
    """
    Recursively find an element anywhere inside
    the formula structure, including fractions.
    """

    for element in elements:

        if str(element.get("id")) == str(element_id):

            return element


        if element.get("type") == "fraction":

            found = find_element(
                element.get("numerator", []),
                element_id
            )

            if found:

                return found


            found = find_element(
                element.get("denominator", []),
                element_id
            )

            if found:

                return found


    return None


def get_hidden_percentage(mastery_level):
    """
    Determine how much of the formula should be tested
    based on the student's mastery level.
    """

    percentages = {

        # Very easy
        0: 10,

        # Easy
        1: 15,

        # Medium
        2: 30,

        # Medium-hard
        3: 45,

        # Hard
        4: 60,

        # Very hard
        5: 80,

        # Full reconstruction
        6: 100,
    }

    return percentages.get(
        mastery_level,
        15
    )


def choose_hidden_elements(
    all_elements,
    mastery_level,
    previous_ids=None
):
    """
    Choose which elements will be hidden.

    Variables, numbers and operators can all be tested.

    The "=" operator has already been removed
    by get_all_elements().
    """

    if not all_elements:

        return []


    percentage = get_hidden_percentage(
        mastery_level
    )


    # ==================================================
    # LEVEL 6
    # ==================================================
    # At maximum mastery, test everything that can
    # reasonably be recalled.
    #
    # "=" is not included in all_elements, so it
    # automatically remains visible.
    # ==================================================

    if percentage >= 100:

        return all_elements.copy()


    # ==================================================
    # CALCULATE NUMBER TO HIDE
    # ==================================================

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


    # Never hide more elements than exist.
    number_to_hide = min(
        number_to_hide,
        len(all_elements)
    )


    previous_ids = previous_ids or []


    # ==================================================
    # AVOID IMMEDIATELY REPEATING ELEMENTS
    # ==================================================

    available = [
        element
        for element in all_elements
        if str(element.get("id"))
        not in previous_ids
    ]


    # If there aren't enough unused elements,
    # fall back to all elements.
    if len(available) < number_to_hide:

        available = all_elements


    return random.sample(
        available,
        number_to_hide
    )

def record_element_performance(
    formula,
    element,
    is_correct
):
    """
    Record whether the student got a specific
    formula element correct or incorrect.
    """

    element_id = str(
        element.get("id", "")
    )

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

    if not element_id:
        return

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

    # Keep the stored information up to date.
    performance.element_type = element_type
    performance.value = value
    performance.last_reviewed = timezone.now()

    if is_correct:

        performance.correct_count += 1

    else:

        performance.incorrect_count += 1

    performance.save()


@login_required
def practice_formula(request, formula_id):

    # ==================================================
    # GET FORMULA
    # ==================================================

    formula = get_object_or_404(
        Formula,
        id=formula_id,
        knowledge_unit__topic__subject__user=request.user
    )


    knowledge_unit = formula.knowledge_unit


    # ==================================================
    # GET STUDENT PROGRESS
    # ==================================================

    progress, created = (
        StudentKnowledge.objects.get_or_create(
            student=request.user,
            knowledge_unit=knowledge_unit,
        )
    )


    # ==================================================
    # LOAD FORMULA STRUCTURE
    # ==================================================

    try:

        formula_elements = json.loads(
            formula.structure
        )

    except (
        json.JSONDecodeError,
        TypeError
    ):

        formula_elements = []


    # ==================================================
    # GET ALL TESTABLE ELEMENTS
    # ==================================================

    all_elements = get_all_elements(
        formula_elements
    )


    hidden_elements = []

    result = None

    correct_answers = {}

    user_answers = {}


    # ==================================================
    # SUBMIT ANSWER
    # ==================================================

    if request.method == "POST":

        hidden_ids = request.POST.getlist(
            "hidden_element_id"
        )


        # ==================================================
        # CHECK EACH HIDDEN ELEMENT
        # ==================================================

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
                user_answer == correct_answer
            )

            user_answers[element_id] = (
                user_answer
            )

            correct_answers[element_id] = (
                correct_answer
            )

            # Record performance for this
            # specific formula element.
            record_element_performance(
                formula,
                element,
                is_correct
            )

        # ==================================================
        # CHECK ALL ANSWERS
        # ==================================================

        all_correct = True


        for element_id in correct_answers:

            user_answer = user_answers.get(
                element_id,
                ""
            )


            correct_answer = (
                correct_answers[element_id]
            )


            if user_answer != correct_answer:

                all_correct = False

                break


        # ==================================================
        # CORRECT
        # ==================================================

        if (
            all_correct
            and correct_answers
        ):

            progress.correct_count += 1


            if progress.mastery_level < 6:

                progress.mastery_level += 1


            progress.review_count += 1

            progress.save()


            # Remember what was tested so the
            # immediate next question tries not
            # to use exactly the same elements.
            previous_ids = list(
                correct_answers.keys()
            )


            hidden_elements = (
                choose_hidden_elements(
                    all_elements,
                    progress.mastery_level,
                    previous_ids
                )
            )


            result = "next"


        # ==================================================
        # INCORRECT
        # ==================================================

        else:

            progress.incorrect_count += 1


            if progress.mastery_level > 0:

                progress.mastery_level -= 1


            progress.review_count += 1

            progress.save()


            # Keep the same elements tested so the
            # student can see what they got wrong.
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


            result = "incorrect"


    # ==================================================
    # NEW QUESTION
    # ==================================================

    else:

        hidden_elements = (
            choose_hidden_elements(
                all_elements,
                progress.mastery_level
            )
        )


    # ==================================================
    # HIDDEN IDS
    # ==================================================

    hidden_ids = [

        str(
            element.get("id")
        )

        for element in hidden_elements

    ]


    # ==================================================
    # RENDER
    # ==================================================

    return render(
        request,
        "practice/practice_formula.html",
        {
            "formula": formula,

            "formula_elements": (
                formula_elements
            ),

            "hidden_elements": (
                hidden_elements
            ),

            "hidden_ids": hidden_ids,

            "progress": progress,

            "result": result,

            "correct_answers": (
                correct_answers
            ),

            "user_answers": (
                user_answers
            ),
        }
    )
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
import json
import random

from learning.models import Formula, StudentKnowledge


def get_all_elements(elements):
    """
    Recursively find every practiceable element,
    including elements inside fractions.
    """

    result = []

    for element in elements:

        if element.get("type") == "fraction":

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

        else:

            result.append(element)

    return result


def find_element(elements, element_id):
    """
    Find an element anywhere in the formula.
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


@login_required
def practice_formula(request, formula_id):

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


    all_elements = get_all_elements(
        formula_elements
    )


    hidden_element = None
    result = None
    correct_answer = ""
    user_answer = ""


    # ==================================================
    # STUDENT SUBMITTED AN ANSWER
    # ==================================================

    if request.method == "POST":

        user_answer = request.POST.get(
            "answer",
            ""
        ).strip()

        hidden_id = request.POST.get(
            "hidden_element_id"
        )


        hidden_element = find_element(
            formula_elements,
            hidden_id
        )


        if hidden_element:

            correct_answer = hidden_element.get(
                "value",
                ""
            ).strip()


        # ----------------------------------------------
        # CORRECT
        # ----------------------------------------------

        if user_answer == correct_answer:

            progress.correct_count += 1

            if progress.mastery_level < 6:

                progress.mastery_level += 1

            progress.review_count += 1

            progress.save()


            # Immediately generate another question.
            available_elements = [
                element
                for element in all_elements
                if element.get("id") != hidden_id
            ]


            if not available_elements:

                available_elements = all_elements


            if available_elements:

                hidden_element = random.choice(
                    available_elements
                )


            result = "next"


        # ----------------------------------------------
        # INCORRECT
        # ----------------------------------------------

        else:

            progress.incorrect_count += 1

            if progress.mastery_level > 0:

                progress.mastery_level -= 1

            progress.review_count += 1

            progress.save()

            result = "incorrect"


    # ==================================================
    # NEW QUESTION
    # ==================================================

    else:

        if all_elements:

            hidden_element = random.choice(
                all_elements
            )


    return render(
        request,
        "practice/practice_formula.html",
        {
            "formula": formula,
            "formula_elements": formula_elements,
            "hidden_element": hidden_element,
            "progress": progress,
            "result": result,
            "correct_answer": correct_answer,
            "user_answer": user_answer,
        }
    )
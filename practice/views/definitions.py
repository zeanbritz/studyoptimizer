from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    render,
    redirect,
    get_object_or_404,
)
from django.utils import timezone

from learning.models import (
    Definition,
    KnowledgeUnit,
    StudentKnowledge,
)


# ============================================================
# DEFINITION MASTERY -> HIDDEN PERCENTAGE
# ============================================================

def get_definition_hidden_percentage(
    mastery_level
):
    """
    Determines how much of the definition should be hidden.

    Uses the same mastery progression as formula practice.
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
        10
    )


# ============================================================
# REVIEW INTERVAL
# ============================================================

def get_definition_review_interval(
    mastery_level
):
    """
    Number of days before the definition becomes due again.
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
# CREATE HIDDEN DEFINITION SECTION
# ============================================================

def create_definition_question(
    definition_text,
    mastery_level
):
    """
    Split a definition into:

        before_text
        missing_text
        after_text

    Higher mastery hides a larger percentage.
    """

    definition_text = (
        definition_text.strip()
    )

    words = definition_text.split()

    # --------------------------------------------------------
    # EMPTY DEFINITION
    # --------------------------------------------------------

    if not words:

        return {
            "before_text": "",
            "missing_text": "",
            "after_text": "",
            "hidden_percentage": 0,
        }

    # --------------------------------------------------------
    # GET MASTERY PERCENTAGE
    # --------------------------------------------------------

    hidden_percentage = (
        get_definition_hidden_percentage(
            mastery_level
        )
    )

    # --------------------------------------------------------
    # MASTERY 6
    #
    # Hide the complete definition.
    # --------------------------------------------------------

    if hidden_percentage >= 100:

        return {
            "before_text": "",
            "missing_text": " ".join(
                words
            ),
            "after_text": "",
            "hidden_percentage":
                hidden_percentage,
        }

    # --------------------------------------------------------
    # CALCULATE HOW MANY WORDS TO HIDE
    # --------------------------------------------------------

    number_to_hide = round(
        len(words)
        * hidden_percentage
        / 100
    )

    number_to_hide = max(
        1,
        number_to_hide
    )

    number_to_hide = min(
        number_to_hide,
        len(words)
    )

    # --------------------------------------------------------
    # HIDE A CONTIGUOUS SECTION AROUND THE MIDDLE
    # --------------------------------------------------------

    middle_index = (
        len(words) // 2
    )

    start_index = (
        middle_index
        - number_to_hide // 2
    )

    start_index = max(
        0,
        start_index
    )

    if (
        start_index
        + number_to_hide
        > len(words)
    ):

        start_index = (
            len(words)
            - number_to_hide
        )

    end_index = (
        start_index
        + number_to_hide
    )

    before_text = " ".join(
        words[
            :start_index
        ]
    )

    missing_text = " ".join(
        words[
            start_index:end_index
        ]
    )

    after_text = " ".join(
        words[
            end_index:
        ]
    )

    return {
        "before_text":
            before_text,

        "missing_text":
            missing_text,

        "after_text":
            after_text,

        "hidden_percentage":
            hidden_percentage,
    }


# ============================================================
# NORMALIZE ANSWER
# ============================================================

def normalize_definition_answer(
    text
):
    """
    Normalize spacing and capitalization before comparison.
    """

    return " ".join(
        text.split()
    ).casefold()


# ============================================================
# PRACTICE DEFINITION
# ============================================================

@login_required
def practice_definition(
    request,
    definition_id
):
    """
    Adaptive definition recall practice.

    Mastery controls how much of the definition is hidden.
    """

    # ========================================================
    # GET DEFINITION
    # ========================================================

    definition = get_object_or_404(
        Definition,
        id=definition_id,
        knowledge_unit__subject__user=request.user
    )

    knowledge_unit = (
        definition.knowledge_unit
    )

    subject = (
        knowledge_unit.subject
    )

    # ========================================================
    # GET OR CREATE PROGRESS
    # ========================================================

    progress, created = (
        StudentKnowledge.objects.get_or_create(
            student=request.user,
            knowledge_unit=knowledge_unit,
        )
    )

    # ========================================================
    # CREATE QUESTION
    # ========================================================

    question = (
        create_definition_question(
            definition.definition,
            progress.mastery_level
        )
    )

    before_text = question[
        "before_text"
    ]

    missing_text = question[
        "missing_text"
    ]

    after_text = question[
        "after_text"
    ]

    hidden_percentage = question[
        "hidden_percentage"
    ]

    # ========================================================
    # CONTINUE TO NEXT DEFINITION
    # ========================================================

    if (
        request.method == "POST"
        and request.POST.get(
            "action"
        ) == "continue"
    ):

        now = timezone.now()

        due_definitions = []

        definitions = (
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
            .select_related(
                "knowledge_unit"
            )
            .order_by(
                "id"
            )
        )

        # ----------------------------------------------------
        # FIND DEFINITIONS THAT ARE DUE
        # ----------------------------------------------------

        for next_definition in definitions:

            next_progress = (
                StudentKnowledge.objects
                .filter(
                    student=request.user,
                    knowledge_unit=(
                        next_definition
                        .knowledge_unit
                    ),
                )
                .first()
            )

            # Never reviewed = due.

            if next_progress is None:

                due_definitions.append(
                    next_definition
                )

                continue

            # Reviewed and due again.

            if (
                next_progress.next_review
                is not None
                and
                next_progress.next_review
                <= now
            ):

                due_definitions.append(
                    next_definition
                )

        # ----------------------------------------------------
        # ANOTHER DEFINITION IS DUE
        # ----------------------------------------------------

        if due_definitions:

            next_definition = (
                due_definitions[0]
            )

            return redirect(
                "practice_definition_review",
                definition_id=(
                    next_definition.id
                )
            )

        # ----------------------------------------------------
        # NO MORE DEFINITIONS
        #
        # Return to subject.
        # ----------------------------------------------------

        subject_index = request.POST.get(
            "subject_index",
            0
        )

        return redirect(
            "subject_detail",
            subject_index=subject_index
        )

    # ========================================================
    # SUBMIT ANSWER
    # ========================================================

    if request.method == "POST":

        answer = request.POST.get(
            "answer",
            ""
        ).strip()

        # ----------------------------------------------------
        # NORMALIZE ANSWERS
        # ----------------------------------------------------

        normalized_answer = (
            normalize_definition_answer(
                answer
            )
        )

        normalized_correct_answer = (
            normalize_definition_answer(
                missing_text
            )
        )

        is_correct = (
            normalized_answer
            == normalized_correct_answer
        )

        # ----------------------------------------------------
        # UPDATE COMMON REVIEW DATA
        # ----------------------------------------------------

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

            interval = (
                get_definition_review_interval(
                    progress.mastery_level
                )
            )

            progress.next_review = (
                timezone.now()
                + timedelta(
                    days=interval
                )
            )

            result = "correct"

        # ====================================================
        # INCORRECT
        # ====================================================

        else:

            progress.incorrect_count += 1

            if progress.mastery_level > 0:

                progress.mastery_level -= 1

            # Incorrect answers return soon.

            progress.next_review = (
                timezone.now()
                + timedelta(
                    days=1
                )
            )

            result = "incorrect"

        progress.save()

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
                == subject.id
            ):

                subject_index = index

                break

        # ----------------------------------------------------
        # FALLBACK TO NAME
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
        # FIND WHETHER ANOTHER DEFINITION IS DUE
        # ====================================================

        now = timezone.now()

        next_definition = None

        definitions = (
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
            .select_related(
                "knowledge_unit"
            )
            .order_by(
                "id"
            )
        )

        for next_item in definitions:

            next_progress = (
                StudentKnowledge.objects
                .filter(
                    student=request.user,
                    knowledge_unit=(
                        next_item.knowledge_unit
                    ),
                )
                .first()
            )

            if next_progress is None:

                next_definition = (
                    next_item
                )

                break

            if (
                next_progress.next_review
                is not None
                and
                next_progress.next_review
                <= now
            ):

                next_definition = (
                    next_item
                )

                break

        # ====================================================
        # SHOW RESULT
        # ====================================================

        return render(
            request,
            "practice/practice_definition.html",
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

                "hidden_percentage":
                    hidden_percentage,

                "answer":
                    answer,

                "is_correct":
                    is_correct,

                "result":
                    result,

                "submitted":
                    True,

                "subject_index":
                    subject_index,

                "next_definition":
                    next_definition,
            }
        )

    # ========================================================
    # FIND SUBJECT INDEX FOR FIRST DISPLAY
    # ========================================================

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
            == subject.id
        ):

            subject_index = index

            break

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

    if subject_index is None:

        subject_index = 0

    # ========================================================
    # DISPLAY QUESTION
    # ========================================================

    return render(
        request,
        "practice/practice_definition.html",
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

            "hidden_percentage":
                hidden_percentage,

            "submitted":
                False,

            "subject_index":
                subject_index,
        }
    )
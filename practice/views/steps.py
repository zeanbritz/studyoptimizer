import random

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    get_object_or_404,
    render,
)
from django.utils import timezone

from learning.models import (
    StepList,
    StudentKnowledge,
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
# NORMALIZE STEP ANSWER
# ============================================================

def normalize_step_answer(
    value
):

    return " ".join(
        str(
            value
            or ""
        )
        .strip()
        .casefold()
        .split()
    )


# ============================================================
# NUMBER OF HIDDEN STEPS
# ============================================================

def get_step_hidden_count(
    total_steps,
    mastery_level
):

    if total_steps <= 0:

        return 0

    mastery_level = max(
        0,
        min(
            6,
            int(
                mastery_level
                or 0
            )
        )
    )

    # --------------------------------------------------------
    # NEW KNOWLEDGE:
    # HIDE ONE STEP
    # --------------------------------------------------------

    if mastery_level == 0:

        return 1

    # --------------------------------------------------------
    # PROGRESSIVELY HIDE MORE
    #
    # 6/6 = ALL STEPS HIDDEN
    # --------------------------------------------------------

    return min(
        total_steps,
        1
        +
        (
            (
                total_steps - 1
            )
            * mastery_level
            // 6
        )
    )


# ============================================================
# FIND NEXT DUE STEP LIST
# ============================================================

def find_next_due_step_list(
    user,
    subject,
    exclude_step_list_id=None,
):

    today = (
        timezone.localdate()
    )

    candidates = (
        StepList.objects
        .filter(
            knowledge_unit__subject=subject,
            knowledge_unit__active=True,
        )
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        )
        .order_by(
            "knowledge_unit__created",
            "id",
        )
    )

    if (
        exclude_step_list_id
        is not None
    ):

        candidates = (
            candidates.exclude(
                id=exclude_step_list_id
            )
        )

    for candidate in candidates:

        progress = (
            StudentKnowledge.objects
            .filter(
                student=user,
                knowledge_unit=(
                    candidate.knowledge_unit
                ),
            )
            .first()
        )

        # ----------------------------------------------------
        # NEVER REVIEWED
        # ----------------------------------------------------

        if progress is None:

            return candidate

        # ----------------------------------------------------
        # NO NEXT DATE
        # ----------------------------------------------------

        if progress.next_review is None:

            return candidate

        # ----------------------------------------------------
        # TODAY OR OVERDUE
        # ----------------------------------------------------

        next_review_date = (
            timezone.localtime(
                progress.next_review
            )
            .date()
        )

        if (
            next_review_date
            <= today
        ):

            return candidate

    return None


# ============================================================
# PRACTICE STEPS
# ============================================================

@login_required
def practice_step_review(
    request,
    step_list_id
):

    # ========================================================
    # STEP LIST
    #
    # IMPORTANT:
    # ONLY ALLOW THE LOGGED-IN USER'S DATA
    # ========================================================

    step_list = get_object_or_404(
        StepList.objects
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        ),
        id=step_list_id,
        knowledge_unit__subject__user=request.user,
        knowledge_unit__active=True,
    )

    knowledge_unit = (
        step_list.knowledge_unit
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
    # STUDENT KNOWLEDGE / MASTERY
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
    # STEPS
    # ========================================================

    steps = list(
        step_list.steps
        .all()
        .order_by(
            "order",
            "id",
        )
    )

    total_steps = len(
        steps
    )

    # ========================================================
    # MASTERY PERCENTAGE
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
    # EMPTY STEP SET
    # ========================================================

    if total_steps == 0:

        return render(
            request,
            "practice/step_review.html",
            {
                "step_list":
                    step_list,

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

                "total_steps":
                    0,

                "hidden_count":
                    0,

                "review_steps":
                    [],

                "error":
                    (
                        "This step set does not "
                        "contain any steps."
                    ),

                "result":
                    None,

                "attempt_complete":
                    False,

                "correct_answers":
                    [],

                "next_step_list":
                    None,
            }
        )

    # ========================================================
    # NUMBER TO HIDE
    # ========================================================

    hidden_count = (
        get_step_hidden_count(
            total_steps,
            progress.mastery_level,
        )
    )

    # ========================================================
    # PAGE STATE
    # ========================================================

    result = None

    error = None

    attempt_complete = False

    correct_answers = []

    next_step_list = None

    hidden_step_ids = []

    submitted_answers = {}

    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        # ====================================================
        # GET HIDDEN STEP IDS
        #
        # KEEP THE SAME RANDOM STEPS THAT WERE SHOWN
        # ON GET.
        # ====================================================

        hidden_step_id_values = (
            request.POST.getlist(
                "hidden_step_id"
            )
        )

        for value in (
            hidden_step_id_values
        ):

            try:

                step_id = int(
                    value
                )

            except (
                TypeError,
                ValueError
            ):

                continue

            if (
                step_id
                not in hidden_step_ids
            ):

                hidden_step_ids.append(
                    step_id
                )

        # ====================================================
        # VALIDATE IDS
        # ====================================================

        valid_step_ids = {
            step.id
            for step
            in steps
        }

        hidden_step_ids = [
            step_id

            for step_id
            in hidden_step_ids

            if step_id
            in valid_step_ids
        ]

        if (
            len(
                hidden_step_ids
            )
            != hidden_count
        ):

            error = (
                "The review changed unexpectedly. "
                "Please reload the page and try again."
            )

        else:

            # =================================================
            # CHECK ANSWERS
            #
            # IMPORTANT DIFFERENCE FROM LISTS:
            #
            # EACH ANSWER IS CHECKED AGAINST THE STEP
            # IN THAT EXACT POSITION.
            #
            # THERE IS NO SORTING.
            # =================================================

            all_correct = True

            correct_answers = []

            for step in steps:

                if (
                    step.id
                    not in hidden_step_ids
                ):

                    continue

                answer_name = (
                    f"answer_{step.id}"
                )

                submitted_answer = (
                    request.POST.get(
                        answer_name,
                        ""
                    )
                )

                submitted_answers[
                    step.id
                ] = submitted_answer

                submitted_normalized = (
                    normalize_step_answer(
                        submitted_answer
                    )
                )

                expected_normalized = (
                    normalize_step_answer(
                        step.text
                    )
                )

                # --------------------------------------------
                # ORDER / POSITION MATTERS
                # --------------------------------------------

                if (
                    submitted_normalized
                    != expected_normalized
                ):

                    all_correct = False

                correct_answers.append(
                    {
                        "number":
                            step.order,

                        "text":
                            step.text,
                    }
                )

            # =================================================
            # COMPLETE ATTEMPT
            # =================================================

            attempt_complete = True

            now = (
                timezone.now()
            )

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

                correct_answers = []

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

            # =================================================
            # NEXT REVIEW
            # =================================================

            interval_days = (
                get_review_interval(
                    progress.mastery_level
                )
            )

            # Even if mastery is 0/6 after an incorrect
            # answer, wait until at least tomorrow.
            interval_days = max(
                1,
                interval_days
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
            # NEXT DUE STEP SET
            #
            # KEEP SUBJECT REVIEW INSIDE THIS SUBJECT
            # =================================================

            next_step_list = (
                find_next_due_step_list(
                    user=request.user,
                    subject=subject,
                    exclude_step_list_id=(
                        step_list.id
                    ),
                )
            )

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
            # RESULT SCREEN
            # =================================================

            return render(
                request,
                "practice/step_review.html",
                {
                    "step_list":
                        step_list,

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

                    "total_steps":
                        total_steps,

                    "hidden_count":
                        hidden_count,

                    "review_steps":
                        [],

                    "error":
                        None,

                    "result":
                        result,

                    "attempt_complete":
                        True,

                    "correct_answers":
                        correct_answers,

                    "next_step_list":
                        next_step_list,
                }
            )

    # ========================================================
    # GET
    # ========================================================

    else:

        hidden_steps = (
            random.sample(
                steps,
                hidden_count
            )
        )

        hidden_step_ids = [
            step.id

            for step
            in hidden_steps
        ]

    # ========================================================
    # BUILD TEMPLATE STEPS
    # ========================================================

    hidden_step_id_set = set(
        hidden_step_ids
    )

    review_steps = []

    for step in steps:

        is_hidden = (
            step.id
            in hidden_step_id_set
        )

        review_steps.append(
            {
                "step":
                    step,

                "hidden":
                    is_hidden,

                "input_name":
                    f"answer_{step.id}",

                "submitted_answer":
                    submitted_answers.get(
                        step.id,
                        ""
                    ),
            }
        )

    # ========================================================
    # RENDER QUESTION
    # ========================================================

    return render(
        request,
        "practice/step_review.html",
        {
            "step_list":
                step_list,

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

            "total_steps":
                total_steps,

            "hidden_count":
                hidden_count,

            "review_steps":
                review_steps,

            "error":
                error,

            "result":
                result,

            "attempt_complete":
                attempt_complete,

            "correct_answers":
                correct_answers,

            "next_step_list":
                next_step_list,
        }
    )
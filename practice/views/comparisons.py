import json
import random

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    get_object_or_404,
    render,
)
from django.utils import timezone

from learning.models import (
    Comparison,
    ComparisonCell,
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
# SUBJECT INDEX
# ============================================================

def get_subject_index(
    request,
    subject
):

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    for index, subject_data in enumerate(
        subjects
    ):

        database_id = subject_data.get(
            "database_id"
        )

        try:

            database_id = int(
                database_id
            )

        except (
            TypeError,
            ValueError
        ):

            database_id = None

        if database_id == subject.id:

            return index

    for index, subject_data in enumerate(
        subjects
    ):

        subject_name = (
            subject_data.get(
                "name",
                ""
            )
            .strip()
        )

        if subject_name == subject.name.strip():

            return index

    return None


# ============================================================
# NEXT DUE COMPARISON
# ============================================================

def find_next_due_comparison(
    user,
    subject,
    exclude_comparison_id=None,
):

    today = timezone.localdate()

    comparisons = (
        Comparison.objects
        .filter(
            knowledge_unit__subject=subject,
            knowledge_unit__active=True,
        )
        .select_related(
            "knowledge_unit"
        )
        .order_by(
            "knowledge_unit__created",
            "id",
        )
    )

    if exclude_comparison_id is not None:

        comparisons = comparisons.exclude(
            id=exclude_comparison_id
        )

    for comparison in comparisons:

        progress = (
            StudentKnowledge.objects
            .filter(
                student=user,
                knowledge_unit=(
                    comparison.knowledge_unit
                ),
            )
            .first()
        )

        if progress is None:

            return comparison

        if progress.next_review is None:

            return comparison

        next_review_date = (
            timezone.localtime(
                progress.next_review
            )
            .date()
        )

        if next_review_date <= today:

            return comparison

    return None


# ============================================================
# PRACTICE COMPARISON
# ============================================================

@login_required
def practice_comparison_review(
    request,
    comparison_id
):

    # ========================================================
    # COMPARISON
    # ========================================================

    comparison = get_object_or_404(
        Comparison.objects
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        )
        .prefetch_related(
            "columns",
            "rows",
            "rows__cells",
        ),
        id=comparison_id,
        knowledge_unit__subject__user=request.user,
        knowledge_unit__active=True,
    )

    knowledge_unit = (
        comparison.knowledge_unit
    )

    subject = (
        knowledge_unit.subject
    )

    # ========================================================
    # SUBJECT INDEX
    # ========================================================

    subject_index = (
        request.POST.get(
            "subject_index"
        )
        or
        request.GET.get(
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

        subject_index = get_subject_index(
            request,
            subject
        )

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
            ),
        ),
    )

    # ========================================================
    # TABLE DATA
    # ========================================================

    columns = list(
        comparison.columns
        .all()
        .order_by(
            "order",
            "id",
        )
    )

    rows = list(
        comparison.rows
        .all()
        .order_by(
            "order",
            "id",
        )
    )

    cells = list(
        ComparisonCell.objects
        .filter(
            row__comparison=comparison
        )
        .select_related(
            "row",
            "column",
        )
        .order_by(
            "row__order",
            "column__order",
            "id",
        )
    )

    # Blank saved cells do not become draggable answers.

    answer_cells = [
        cell
        for cell in cells
        if cell.content.strip()
    ]

    cell_lookup = {
        cell.id:
            cell
        for cell in answer_cells
    }

    row_lookup = {
        row.id:
            row
        for row in rows
    }

    column_lookup = {
        column.id:
            column
        for column in columns
    }

    valid_row_ids = set(
        row_lookup.keys()
    )

    valid_column_ids = set(
        column_lookup.keys()
    )

    # ========================================================
    # PAGE STATE
    # ========================================================

    result = None
    error = None
    attempt_complete = False
    next_comparison = None

    placed_by_position = {}
    incorrect_explanations = []

    # ========================================================
    # CHECK ANSWER
    # ========================================================

    if request.method == "POST":

        placements_raw = (
            request.POST.get(
                "placements",
                ""
            )
        )

        normalized_placements = {}

        try:

            submitted_placements = (
                json.loads(
                    placements_raw
                )
            )

            if not isinstance(
                submitted_placements,
                dict
            ):

                raise ValueError

            for (
                cell_id_raw,
                destination
            ) in submitted_placements.items():

                if not isinstance(
                    destination,
                    dict
                ):

                    raise ValueError

                cell_id = int(
                    cell_id_raw
                )

                row_id = int(
                    destination.get(
                        "row_id"
                    )
                )

                column_id = int(
                    destination.get(
                        "column_id"
                    )
                )

                normalized_placements[
                    cell_id
                ] = {
                    "row_id":
                        row_id,

                    "column_id":
                        column_id,
                }

        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):

            error = (
                "The answer could not be checked. "
                "Please reload and try again."
            )

        expected_cell_ids = set(
            cell_lookup.keys()
        )

        submitted_cell_ids = set(
            normalized_placements.keys()
        )

        # ----------------------------------------------------
        # EVERY FIELD MUST BE PLACED
        # ----------------------------------------------------

        if (
            error is None
            and
            submitted_cell_ids
            !=
            expected_cell_ids
        ):

            error = (
                "Place every field into the table "
                "before checking your answer."
            )

        # ----------------------------------------------------
        # VALID DESTINATIONS
        # ----------------------------------------------------

        used_positions = set()

        if error is None:

            for destination in (
                normalized_placements.values()
            ):

                row_id = destination[
                    "row_id"
                ]

                column_id = destination[
                    "column_id"
                ]

                position = (
                    row_id,
                    column_id,
                )

                if (
                    row_id not in valid_row_ids
                    or
                    column_id not in valid_column_ids
                ):

                    error = (
                        "The comparison changed. "
                        "Please reload and try again."
                    )

                    break

                if position in used_positions:

                    error = (
                        "Only one field can be placed "
                        "in each table position."
                    )

                    break

                used_positions.add(
                    position
                )

        # ====================================================
        # MARK ANSWERS
        # ====================================================

        if error is None:

            all_correct = True

            for cell in answer_cells:

                destination = (
                    normalized_placements[
                        cell.id
                    ]
                )

                placed_row_id = (
                    destination[
                        "row_id"
                    ]
                )

                placed_column_id = (
                    destination[
                        "column_id"
                    ]
                )

                column_correct = (
                    placed_column_id
                    ==
                    cell.column_id
                )

                # Named rows must match exactly.
                # Unnamed rows may be placed in any row.

                row_correct = (
                    not cell.row.name.strip()
                    or
                    placed_row_id == cell.row_id
                )

                answer_correct = (
                    column_correct
                    and
                    row_correct
                )

                if not answer_correct:

                    all_correct = False

                placed_by_position[
                    (
                        placed_row_id,
                        placed_column_id,
                    )
                ] = {
                    "content":
                        cell.content,

                    "is_correct":
                        answer_correct,
                }

                # --------------------------------------------
                # EXPLAIN INCORRECT ANSWERS
                # --------------------------------------------

                if not answer_correct:

                    correct_location = (
                        cell.column.name
                    )

                    if cell.row.name.strip():

                        correct_location = (
                            f"{correct_location} "
                            f"→ {cell.row.name}"
                        )

                    else:

                        correct_location = (
                            f"{correct_location} "
                            f"→ any row"
                        )

                    placed_row = (
                        row_lookup[
                            placed_row_id
                        ]
                    )

                    placed_column = (
                        column_lookup[
                            placed_column_id
                        ]
                    )

                    placed_row_name = (
                        placed_row.name.strip()
                        or
                        "unnamed row"
                    )

                    incorrect_explanations.append(
                        {
                            "content":
                                cell.content,

                            "placed":
                                (
                                    f"{placed_column.name} "
                                    f"→ {placed_row_name}"
                                ),

                            "correct":
                                correct_location,
                        }
                    )

            # =================================================
            # UPDATE PROGRESS
            # =================================================

            attempt_complete = True

            now = timezone.now()

            progress.review_count = (
                progress.review_count
                +
                1
            )

            progress.last_reviewed = now

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
                    ),
                )

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
                    ),
                )

            interval_days = max(
                1,
                get_review_interval(
                    progress.mastery_level
                ),
            )

            progress.next_review = (
                now
                +
                timedelta(
                    days=interval_days
                )
            )

            progress.save()

            next_comparison = (
                find_next_due_comparison(
                    user=request.user,
                    subject=subject,
                    exclude_comparison_id=(
                        comparison.id
                    ),
                )
            )

    # ========================================================
    # SHUFFLED ANSWER BANK
    # ========================================================

    shuffled_cells = []

    if not attempt_complete:

        shuffled_cells = list(
            answer_cells
        )

        random.shuffle(
            shuffled_cells
        )

    if not answer_cells:

        error = (
            "This comparison does not contain "
            "any filled fields to review."
        )

    # ========================================================
    # BUILD BOARD
    # ========================================================

    review_rows = []

    for row in rows:

        slots = []

        for column in columns:

            slots.append(
                {
                    "column":
                        column,

                    "placed":
                        placed_by_position.get(
                            (
                                row.id,
                                column.id,
                            )
                        ),
                }
            )

        review_rows.append(
            {
                "row":
                    row,

                "slots":
                    slots,
            }
        )

    mastery_percentage = round(
        (
            progress.mastery_level
            /
            6
        )
        *
        100
    )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "practice/comparison_review.html",
        {
            "comparison":
                comparison,

            "subject":
                subject,

            "subject_index":
                subject_index,

            "columns":
                columns,

            "review_rows":
                review_rows,

            "shuffled_cells":
                shuffled_cells,

            "total_fields":
                len(
                    answer_cells
                ),

            "result":
                result,

            "error":
                error,

            "attempt_complete":
                attempt_complete,

            "incorrect_explanations":
                incorrect_explanations,

            "next_comparison":
                next_comparison,

            "mastery_level":
                progress.mastery_level,

            "mastery_percentage":
                mastery_percentage,
        }
    )
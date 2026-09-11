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
# NORMALIZE CHARACTERISTIC
# ============================================================

def normalize_characteristic(
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
# NEXT GLOBAL COMPARISON
#
# ALL ACTIVE COMPARISONS ACROSS ALL SUBJECTS.
# DUE DATE DOES NOT MATTER IN GLOBAL REVIEW.
# ============================================================

def find_next_global_comparison(
    user,
    current_comparison_id,
):

    comparisons = list(
        Comparison.objects
        .filter(
            knowledge_unit__subject__user=user,
            knowledge_unit__active=True,
        )
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        )
        .order_by(
            "knowledge_unit__subject__name",
            "knowledge_unit__created",
            "id",
        )
    )

    current_position = None

    for index, comparison in enumerate(
        comparisons
    ):

        if comparison.id == current_comparison_id:

            current_position = index

            break

    if current_position is None:

        return None

    next_position = current_position + 1

    if next_position >= len(comparisons):

        return None

    return comparisons[next_position]


# ============================================================
# PRACTICE COMPARISON
# ============================================================

@login_required
def practice_comparison_review(
    request,
    comparison_id
):

    # ========================================================
    # REVIEW SCOPE
    #
    # subject = due comparisons from one subject
    # all     = every active comparison across all subjects
    # ========================================================

    review_scope = (
        request.GET.get(
            "scope"
        )
        or
        request.POST.get(
            "scope"
        )
        or
        "subject"
    )

    if review_scope != "all":

        review_scope = "subject"

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

    has_named_rows = any(
        row.name.strip()
        for row in rows
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

            # Identical characteristic text is interchangeable.
            # A submitted field is correct when its destination
            # matches any unused saved cell with the same text.

            expected_by_content = {}

            for expected_cell in answer_cells:

                content_key = (
                    normalize_characteristic(
                        expected_cell.content
                    )
                )

                expected_by_content.setdefault(
                    content_key,
                    [],
                ).append(
                    expected_cell
                )

            placement_records = []

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

                content_key = (
                    normalize_characteristic(
                        cell.content
                    )
                )

                matching_cells = [
                    expected_cell
                    for expected_cell
                    in expected_by_content.get(
                        content_key,
                        [],
                    )
                    if (
                        expected_cell.column_id
                        == placed_column_id
                        and
                        (
                            not expected_cell.row.name.strip()
                            or
                            expected_cell.row_id
                            == placed_row_id
                        )
                    )
                ]

                placement_records.append(
                    {
                        "cell":
                            cell,

                        "row_id":
                            placed_row_id,

                        "column_id":
                            placed_column_id,

                        "matching_cells":
                            matching_cells,
                    }
                )

            # Check the most restricted destinations first so a
            # flexible unnamed-row match cannot take a named-row
            # answer needed by another identical characteristic.

            placement_records.sort(
                key=lambda record: (
                    len(
                        record[
                            "matching_cells"
                        ]
                    ),
                    record[
                        "cell"
                    ].id,
                )
            )

            used_expected_cell_ids = set()

            for record in placement_records:

                cell = record[
                    "cell"
                ]

                placed_row_id = record[
                    "row_id"
                ]

                placed_column_id = record[
                    "column_id"
                ]

                available_matches = [
                    expected_cell
                    for expected_cell
                    in record[
                        "matching_cells"
                    ]
                    if expected_cell.id
                    not in used_expected_cell_ids
                ]

                answer_correct = bool(
                    available_matches
                )

                if answer_correct:

                    # Prefer a named exact-row match. This keeps
                    # unnamed-row answers available for other rows.

                    available_matches.sort(
                        key=lambda expected_cell: (
                            1
                            if not expected_cell.row.name.strip()
                            else 0,
                            expected_cell.id,
                        )
                    )

                    matched_cell = (
                        available_matches[0]
                    )

                    used_expected_cell_ids.add(
                        matched_cell.id
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

                    content_key = (
                        normalize_characteristic(
                            cell.content
                        )
                    )

                    correct_locations = []

                    for expected_cell in (
                        expected_by_content.get(
                            content_key,
                            [],
                        )
                    ):

                        location = (
                            expected_cell.column.name
                        )

                        if has_named_rows:

                            if expected_cell.row.name.strip():

                                location = (
                                    f"{location} "
                                    f"→ {expected_cell.row.name}"
                                )

                            else:

                                location = (
                                    f"{location} "
                                    f"→ any row"
                                )

                        if location not in correct_locations:

                            correct_locations.append(
                                location
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

                    placed_location = (
                        placed_column.name
                    )

                    if has_named_rows:

                        placed_row_name = (
                            placed_row.name.strip()
                            or
                            "unnamed row"
                        )

                        placed_location = (
                            f"{placed_location} "
                            f"→ {placed_row_name}"
                        )

                    incorrect_explanations.append(
                        {
                            "content":
                                cell.content,

                            "placed":
                                placed_location,

                            "correct":
                                "; ".join(
                                    correct_locations
                                ),
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

            if review_scope == "all":

                next_comparison = (
                    find_next_global_comparison(
                        user=request.user,
                        current_comparison_id=(
                            comparison.id
                        ),
                    )
                )

            else:

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

            "review_scope":
                review_scope,

            "columns":
                columns,

            "review_rows":
                review_rows,

            "has_named_rows":
                has_named_rows,

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

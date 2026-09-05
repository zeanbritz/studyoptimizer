from collections import Counter
from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone

from learning.models import (
    Subject,
    KnowledgeUnit,
    Formula,
    Definition,
    BulletList,
    StepList,
    StudentKnowledge,
    Note,
)

from .models import (
    StudyAvailability,
    SubjectTextbook,
    SubjectRevisionPlan,
)


# ============================================================
# DASHBOARD
# ============================================================

@login_required
def dashboard(request):

    # --------------------------------------------------------
    # ONBOARDING
    # --------------------------------------------------------

    onboarding_complete = (
        request.session.get(
            "onboarding_complete",
            False
        )
    )

    # --------------------------------------------------------
    # TODAY
    # --------------------------------------------------------

    today = timezone.localdate()

    # --------------------------------------------------------
    # SESSION SUBJECTS
    # --------------------------------------------------------

    session_subjects = (
        request.session.get(
            "onboarding_subjects",
            []
        )
    )

    # --------------------------------------------------------
    # DEFINITION DATA
    # --------------------------------------------------------

    due_definition_subjects = []
    due_definition_total = 0

    # --------------------------------------------------------
    # FORMULA DATA
    # --------------------------------------------------------

    due_formula_subjects = []
    due_formula_total = 0

    # --------------------------------------------------------
    # LIST DATA
    # --------------------------------------------------------

    due_list_subjects = []
    due_list_total = 0

    # --------------------------------------------------------
    # BOOK SUMMARY DATA
    # --------------------------------------------------------

    book_summary_subjects = []
    book_summary_total = 0

    # --------------------------------------------------------
    # STEP DATA
    # --------------------------------------------------------

    due_step_subjects = []
    due_step_total = 0

    # --------------------------------------------------------
    # NOTE DATA
    # --------------------------------------------------------

    note_subjects = []
    note_total = 0

    # ========================================================
    # HELPER:
    # FIND SESSION SUBJECT INDEX
    # ========================================================

    def find_subject_index(
        database_subject
    ):

        # ----------------------------------------------------
        # FIRST TRY DATABASE ID
        # ----------------------------------------------------

        for (
            index,
            subject_data
        ) in enumerate(
            session_subjects
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

                database_id = None

            if (
                database_id
                ==
                database_subject.id
            ):

                return index

        # ----------------------------------------------------
        # FALLBACK TO SUBJECT NAME
        # ----------------------------------------------------

        for (
            index,
            subject_data
        ) in enumerate(
            session_subjects
        ):

            session_name = (
                subject_data.get(
                    "name",
                    ""
                )
                .strip()
            )

            if (
                session_name
                ==
                database_subject.name.strip()
            ):

                return index

        return None

    # ========================================================
    # ONLY BUILD PLAN AFTER ONBOARDING
    # ========================================================

    if onboarding_complete:

        # ====================================================
        # DEFINITIONS
        # ====================================================

        definition_knowledge_units = (
            KnowledgeUnit.objects
            .filter(
                subject__user=request.user,
                knowledge_type=(
                    KnowledgeUnit
                    .KnowledgeType
                    .DEFINITION
                ),
                active=True,
            )
            .select_related(
                "definition",
                "subject",
            )
            .order_by(
                "subject__name",
                "definition__term",
            )
        )

        definition_groups = {}

        # ----------------------------------------------------
        # CHECK EACH DEFINITION
        # ----------------------------------------------------

        for knowledge_unit in (
            definition_knowledge_units
        ):

            definition = getattr(
                knowledge_unit,
                "definition",
                None
            )

            if not definition:

                continue

            # ------------------------------------------------
            # PROGRESS
            # ------------------------------------------------

            progress = (
                StudentKnowledge.objects
                .filter(
                    student=request.user,
                    knowledge_unit=knowledge_unit,
                )
                .first()
            )

            # ------------------------------------------------
            # IS DUE?
            # ------------------------------------------------

            is_due = False

            if progress is None:

                is_due = True

            elif progress.next_review is None:

                is_due = True

            else:

                next_review_date = (
                    timezone.localtime(
                        progress.next_review
                    )
                    .date()
                )

                if (
                    next_review_date
                    <=
                    today
                ):

                    is_due = True

            if not is_due:

                continue

            # ------------------------------------------------
            # SUBJECT
            # ------------------------------------------------

            database_subject = (
                knowledge_unit.subject
            )

            if not database_subject:

                continue

            # ------------------------------------------------
            # SUBJECT INDEX
            # ------------------------------------------------

            subject_index = (
                find_subject_index(
                    database_subject
                )
            )

            if subject_index is None:

                continue

            # ------------------------------------------------
            # GROUP BY SUBJECT
            # ------------------------------------------------

            subject_id = (
                database_subject.id
            )

            if (
                subject_id
                not in
                definition_groups
            ):

                definition_groups[
                    subject_id
                ] = {

                    "subject":
                        database_subject,

                    "subject_index":
                        subject_index,

                    "count":
                        0,
                }

            definition_groups[
                subject_id
            ][
                "count"
            ] += 1

            due_definition_total += 1

        due_definition_subjects = list(
            definition_groups.values()
        )

        # ====================================================
        # FORMULAS
        # ====================================================

        formula_knowledge_units = (
            KnowledgeUnit.objects
            .filter(
                subject__user=request.user,
                knowledge_type=(
                    KnowledgeUnit
                    .KnowledgeType
                    .FORMULA
                ),
                active=True,
            )
            .select_related(
                "formula",
                "subject",
            )
            .order_by(
                "subject__name",
                "created",
            )
        )

        formula_groups = {}

        for knowledge_unit in (
            formula_knowledge_units
        ):

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
                    knowledge_unit=knowledge_unit,
                )
                .first()
            )

            is_due = False

            if progress is None:

                is_due = True

            elif progress.next_review is None:

                is_due = True

            else:

                next_review_date = (
                    timezone.localtime(
                        progress.next_review
                    )
                    .date()
                )

                if (
                    next_review_date
                    <=
                    today
                ):

                    is_due = True

            if not is_due:

                continue

            database_subject = (
                knowledge_unit.subject
            )

            if not database_subject:

                continue

            subject_index = (
                find_subject_index(
                    database_subject
                )
            )

            if subject_index is None:

                continue

            subject_id = (
                database_subject.id
            )

            if (
                subject_id
                not in
                formula_groups
            ):

                formula_groups[
                    subject_id
                ] = {

                    "subject":
                        database_subject,

                    "subject_index":
                        subject_index,

                    "count":
                        0,
                }

            formula_groups[
                subject_id
            ][
                "count"
            ] += 1

            due_formula_total += 1

        due_formula_subjects = list(
            formula_groups.values()
        )

        # ====================================================
        # LISTS
        # ====================================================

        bullet_lists = (
            BulletList.objects
            .filter(
                knowledge_unit__subject__user=request.user,
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

        list_groups = {}

        for bullet_list in (
            bullet_lists
        ):

            knowledge_unit = (
                bullet_list.knowledge_unit
            )

            progress = (
                StudentKnowledge.objects
                .filter(
                    student=request.user,
                    knowledge_unit=knowledge_unit,
                )
                .first()
            )

            is_due = False

            if progress is None:

                is_due = True

            elif progress.next_review is None:

                is_due = True

            else:

                next_review_date = (
                    timezone.localtime(
                        progress.next_review
                    )
                    .date()
                )

                if (
                    next_review_date
                    <=
                    today
                ):

                    is_due = True

            if not is_due:

                continue

            database_subject = (
                knowledge_unit.subject
            )

            if not database_subject:

                continue

            subject_index = (
                find_subject_index(
                    database_subject
                )
            )

            if subject_index is None:

                continue

            subject_id = (
                database_subject.id
            )

            if (
                subject_id
                not in
                list_groups
            ):

                list_groups[
                    subject_id
                ] = {

                    "subject":
                        database_subject,

                    "subject_index":
                        subject_index,

                    "count":
                        0,
                }

            list_groups[
                subject_id
            ][
                "count"
            ] += 1

            due_list_total += 1

        due_list_subjects = list(
            list_groups.values()
        )

        # ====================================================
        # STEPS
        # ====================================================

        step_lists = (
            StepList.objects
            .filter(
                knowledge_unit__subject__user=request.user,
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

        step_groups = {}

        for step_list in (
            step_lists
        ):

            knowledge_unit = (
                step_list.knowledge_unit
            )

            progress = (
                StudentKnowledge.objects
                .filter(
                    student=request.user,
                    knowledge_unit=knowledge_unit,
                )
                .first()
            )

            is_due = False

            if progress is None:

                is_due = True

            elif progress.next_review is None:

                is_due = True

            else:

                next_review_date = (
                    timezone.localtime(
                        progress.next_review
                    )
                    .date()
                )

                if (
                    next_review_date
                    <=
                    today
                ):

                    is_due = True

            if not is_due:

                continue

            database_subject = (
                knowledge_unit.subject
            )

            if not database_subject:

                continue

            subject_index = (
                find_subject_index(
                    database_subject
                )
            )

            if subject_index is None:

                continue

            subject_id = (
                database_subject.id
            )

            if (
                subject_id
                not in
                step_groups
            ):

                step_groups[
                    subject_id
                ] = {

                    "subject":
                        database_subject,

                    "subject_index":
                        subject_index,

                    "count":
                        0,
                }

            step_groups[
                subject_id
            ][
                "count"
            ] += 1

            due_step_total += 1

        due_step_subjects = list(
            step_groups.values()
        )

        # ====================================================
        # NOTES
        # ====================================================

        notes = (
            Note.objects
            .filter(
                subject__user=request.user
            )
            .select_related(
                "subject"
            )
            .order_by(
                "subject__name",
                "created",
                "id",
            )
        )

        note_groups = {}

        # ----------------------------------------------------
        # GROUP NOTES BY SUBJECT
        # ----------------------------------------------------

        for note in notes:

            database_subject = (
                note.subject
            )

            if not database_subject:

                continue

            # ------------------------------------------------
            # SUBJECT INDEX
            # ------------------------------------------------

            subject_index = (
                find_subject_index(
                    database_subject
                )
            )

            if subject_index is None:

                continue

            # ------------------------------------------------
            # GROUP
            # ------------------------------------------------

            subject_id = (
                database_subject.id
            )

            if (
                subject_id
                not in
                note_groups
            ):

                note_groups[
                    subject_id
                ] = {

                    "subject":
                        database_subject,

                    "subject_index":
                        subject_index,

                    "count":
                        0,
                }

            note_groups[
                subject_id
            ][
                "count"
            ] += 1

            note_total += 1

        # ----------------------------------------------------
        # FINAL NOTE SUBJECTS
        # ----------------------------------------------------

        note_subjects = list(
            note_groups.values()
        )

        # ====================================================
        # BOOK SUMMARIES
        # ====================================================

        from learning.views import (
            calculate_book_summary_targets,
        )

        for (
            subject_index,
            subject_data
        ) in enumerate(
            session_subjects
        ):

            database_subject = None

            database_subject_id = (
                subject_data.get(
                    "database_id"
                )
            )

            try:

                database_subject_id = int(
                    database_subject_id
                )

            except (
                TypeError,
                ValueError
            ):

                database_subject_id = None

            if database_subject_id:

                database_subject = (
                    Subject.objects
                    .filter(
                        id=database_subject_id,
                        user=request.user,
                    )
                    .first()
                )

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

                continue

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

            if not textbooks:

                continue

            schedule_data = (
                calculate_book_summary_targets(
                    request=request,
                    subject=database_subject,
                    subject_data=subject_data,
                    textbooks=textbooks,
                )
            )

            book_items = (
                schedule_data.get(
                    "book_items",
                    []
                )
            )

            unfinished_books_today = []
            pages_left_today = 0

            for item in book_items:

                if item.get(
                    "complete",
                    False
                ):

                    continue

                if item.get(
                    "completed_today",
                    False
                ):

                    continue

                target_pages = int(
                    item.get(
                        "target_pages",
                        0
                    )
                    or 0
                )

                if target_pages <= 0:

                    continue

                unfinished_books_today.append(
                    item
                )

                pages_left_today += (
                    target_pages
                )

            if not unfinished_books_today:

                continue

            book_summary_subjects.append(
                {
                    "subject":
                        database_subject,

                    "subject_index":
                        subject_index,

                    "count":
                        len(
                            unfinished_books_today
                        ),

                    "pages":
                        pages_left_today,
                }
            )

        book_summary_total = len(
            book_summary_subjects
        )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "dashboard/dashboard.html",
        {
            # --------------------------------------------
            # ONBOARDING
            # --------------------------------------------

            "onboarding_complete":
                onboarding_complete,

            # --------------------------------------------
            # DEFINITIONS
            # --------------------------------------------

            "due_definition_subjects":
                due_definition_subjects,

            "due_definition_total":
                due_definition_total,

            # --------------------------------------------
            # FORMULAS
            # --------------------------------------------

            "due_formula_subjects":
                due_formula_subjects,

            "due_formula_total":
                due_formula_total,

            # --------------------------------------------
            # LISTS
            # --------------------------------------------

            "due_list_subjects":
                due_list_subjects,

            "due_list_total":
                due_list_total,

            # --------------------------------------------
            # STEPS
            # --------------------------------------------

            "due_step_subjects":
                due_step_subjects,

            "due_step_total":
                due_step_total,

            # --------------------------------------------
            # NOTES
            # --------------------------------------------

            "note_subjects":
                note_subjects,

            "note_total":
                note_total,

            # --------------------------------------------
            # BOOK SUMMARIES
            # --------------------------------------------

            "book_summary_subjects":
                book_summary_subjects,

            "book_summary_total":
                book_summary_total,
        }
    )
    
# ============================================================
# REVIEW
# ============================================================

@login_required
def review(request):

    # ========================================================
    # SUBJECTS
    # ========================================================

    subjects = (
        Subject.objects
        .filter(
            user=request.user
        )
        .order_by(
            "name"
        )
    )

    # ========================================================
    # DEFINITIONS
    # ========================================================

    definition_knowledge_units = (
        KnowledgeUnit.objects
        .filter(
            subject__user=request.user,
            knowledge_type=(
                KnowledgeUnit
                .KnowledgeType
                .DEFINITION
            ),
            active=True,
        )
        .select_related(
            "definition",
            "subject",
        )
        .order_by(
            "subject__name",
            "created",
        )
    )

    definitions = []

    for knowledge_unit in (
        definition_knowledge_units
    ):

        definition = getattr(
            knowledge_unit,
            "definition",
            None
        )

        if definition:

            definitions.append(
                definition
            )

    # ========================================================
    # FORMULAS
    # ========================================================

    formula_knowledge_units = (
        KnowledgeUnit.objects
        .filter(
            subject__user=request.user,
            knowledge_type=(
                KnowledgeUnit
                .KnowledgeType
                .FORMULA
            ),
            active=True,
        )
        .select_related(
            "formula",
            "subject",
        )
        .order_by(
            "subject__name",
            "created",
        )
    )

    formulas = []

    for knowledge_unit in (
        formula_knowledge_units
    ):

        formula = getattr(
            knowledge_unit,
            "formula",
            None
        )

        if formula:

            formulas.append(
                formula
            )

    # ========================================================
    # NOTES
    # ========================================================

    notes = (
        Note.objects
        .filter(
            subject__user=request.user
        )
        .select_related(
            "subject"
        )
        .order_by(
            "subject__name",
            "created",
            "id",
        )
    )

    # ========================================================
    # COUNTS
    # ========================================================

    definition_count = len(
        definitions
    )

    formula_count = len(
        formulas
    )

    note_count = (
        notes.count()
    )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "dashboard/review.html",
        {
            "subjects":
                subjects,

            # --------------------------------------------
            # DEFINITIONS
            # --------------------------------------------

            "definitions":
                definitions,

            "definition_count":
                definition_count,

            # --------------------------------------------
            # FORMULAS
            # --------------------------------------------

            "formulas":
                formulas,

            "formula_count":
                formula_count,

            # --------------------------------------------
            # NOTES
            # --------------------------------------------

            "notes":
                notes,

            "note_count":
                note_count,
        }
    )

# ============================================================
# ONBOARDING
# ============================================================

@login_required
def onboarding(request):

    if request.method == "POST":

        workspace_name = (
            request.POST.get(
                "workspace_name",
                ""
            )
            .strip()
        )

        target_grade = request.POST.get(
            "target_grade",
            ""
        )

        study_hours = request.POST.get(
            "study_hours",
            ""
        )

        subject_count = request.POST.get(
            "subject_count",
            "1"
        )

        try:

            subject_count = int(
                subject_count
            )

        except (
            ValueError,
            TypeError
        ):

            subject_count = 1

        subject_count = max(
            1,
            min(
                subject_count,
                20
            )
        )

        request.session[
            "onboarding_profile"
        ] = {

            "workspace_name":
                workspace_name,

            "target_grade":
                target_grade,

            "study_hours":
                study_hours,

            "subject_count":
                subject_count,
        }

        subjects = []

        for i in range(
            subject_count
        ):

            subjects.append(
                {
                    "name":
                        "",

                    "target_grade":
                        "",

                    "exam_date":
                        "",

                    "definitions":
                        [],

                    "formulas":
                        [],

                    "database_id":
                        None,
                }
            )

        request.session[
            "onboarding_subjects"
        ] = subjects

        request.session[
            "onboarding_complete"
        ] = True

        request.session.modified = True

        return redirect(
            "goals"
        )

    return render(
        request,
        "dashboard/onboarding.html"
    )


# ============================================================
# GOALS
# ============================================================

@login_required
def goals(request):

    profile = request.session.get(
        "onboarding_profile"
    )

    if not profile:

        return redirect(
            "onboarding"
        )

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    days = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]

    # ========================================================
    # STUDY AVAILABILITY
    # ========================================================

    availability_record, created = (
        StudyAvailability.objects
        .get_or_create(
            user=request.user
        )
    )

    study_availability = {}

    for day in days:

        study_availability[
            day
        ] = {

            "enabled":
                getattr(
                    availability_record,
                    f"{day}_enabled"
                ),

            "time":
                getattr(
                    availability_record,
                    f"{day}_time"
                ),
        }

    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        action = request.POST.get(
            "action",
            ""
        )

        # ====================================================
        # UPDATE PROFILE
        # ====================================================

        if action == "update_profile":

            workspace_name = (
                request.POST.get(
                    "workspace_name",
                    ""
                )
                .strip()
            )

            target_grade = (
                request.POST.get(
                    "target_grade",
                    ""
                )
                .strip()
            )

            if workspace_name:

                profile[
                    "workspace_name"
                ] = workspace_name

            try:

                target_grade = int(
                    target_grade
                )

                target_grade = max(
                    0,
                    min(
                        target_grade,
                        100
                    )
                )

                profile[
                    "target_grade"
                ] = target_grade

            except (
                TypeError,
                ValueError
            ):

                pass

            profile[
                "subject_count"
            ] = len(
                subjects
            )

            request.session[
                "onboarding_profile"
            ] = profile

            request.session.modified = True

            return redirect(
                "goals"
            )

        # ====================================================
        # LEGACY TARGET
        # ====================================================

        elif action == "update_target":

            target_grade = (
                request.POST.get(
                    "target_grade",
                    ""
                )
                .strip()
            )

            try:

                target_grade = int(
                    target_grade
                )

                target_grade = max(
                    0,
                    min(
                        target_grade,
                        100
                    )
                )

                profile[
                    "target_grade"
                ] = target_grade

            except (
                TypeError,
                ValueError
            ):

                pass

            request.session[
                "onboarding_profile"
            ] = profile

            request.session.modified = True

            return redirect(
                "goals"
            )

        # ====================================================
        # AUTOSAVE AVAILABILITY
        # ====================================================

        elif action == "update_availability":

            errors = {}

            for day in days:

                enabled = (
                    request.POST.get(
                        f"{day}_enabled",
                        "0"
                    )
                    ==
                    "1"
                )

                raw_time = (
                    request.POST.get(
                        f"{day}_time",
                        ""
                    )
                    .strip()
                )

                if not enabled:

                    setattr(
                        availability_record,
                        f"{day}_enabled",
                        False
                    )

                    setattr(
                        availability_record,
                        f"{day}_time",
                        ""
                    )

                    continue

                setattr(
                    availability_record,
                    f"{day}_enabled",
                    True
                )

                if raw_time == "":

                    setattr(
                        availability_record,
                        f"{day}_time",
                        ""
                    )

                    continue

                try:

                    parts = raw_time.split(
                        ":"
                    )

                    if len(parts) != 2:

                        raise ValueError

                    hours = int(
                        parts[0]
                    )

                    minutes = int(
                        parts[1]
                    )

                    if (
                        hours < 0
                        or
                        hours > 24
                    ):

                        raise ValueError

                    if (
                        minutes < 0
                        or
                        minutes > 59
                    ):

                        raise ValueError

                    if (
                        hours == 24
                        and
                        minutes != 0
                    ):

                        raise ValueError

                    normalized_time = (
                        f"{hours:02d}:"
                        f"{minutes:02d}"
                    )

                    setattr(
                        availability_record,
                        f"{day}_time",
                        normalized_time
                    )

                except (
                    TypeError,
                    ValueError
                ):

                    errors[
                        day
                    ] = (
                        "Enter a valid time "
                        "between 00:00 and 24:00."
                    )

            if errors:

                return JsonResponse(
                    {
                        "success":
                            False,

                        "errors":
                            errors,
                    },
                    status=400,
                )

            availability_record.save()

            if (
                request.headers.get(
                    "X-Requested-With"
                )
                ==
                "XMLHttpRequest"
            ):

                return JsonResponse(
                    {
                        "success":
                            True,
                    }
                )

            return redirect(
                "goals"
            )

        # ====================================================
        # ADD SUBJECT
        # ====================================================

        elif action == "add_subject":

            if len(subjects) >= 20:

                return redirect(
                    "goals"
                )

            new_subject = {

                "name":
                    "",

                "target_grade":
                    "",

                "exam_date":
                    "",

                "definitions":
                    [],

                "formulas":
                    [],

                "database_id":
                    None,
            }

            subjects.append(
                new_subject
            )

            profile[
                "subject_count"
            ] = len(
                subjects
            )

            request.session[
                "onboarding_subjects"
            ] = subjects

            request.session[
                "onboarding_profile"
            ] = profile

            request.session.modified = True

            new_subject_index = (
                len(subjects)
                -
                1
            )

            return redirect(
                "subject_detail",
                subject_index=(
                    new_subject_index
                )
            )

    # ========================================================
    # REFRESH AVAILABILITY
    # ========================================================

    study_availability = {}

    for day in days:

        study_availability[
            day
        ] = {

            "enabled":
                getattr(
                    availability_record,
                    f"{day}_enabled"
                ),

            "time":
                getattr(
                    availability_record,
                    f"{day}_time"
                ),
        }

    # ========================================================
    # DAYS UNTIL EXAM
    # ========================================================

    today = timezone.localdate()

    display_subjects = []

    for subject in subjects:

        subject_data = dict(
            subject
        )

        exam_date = (
            subject_data.get(
                "exam_date"
            )
        )

        days_until_exam = None

        if exam_date:

            try:

                if isinstance(
                    exam_date,
                    datetime
                ):

                    parsed_exam_date = (
                        exam_date.date()
                    )

                elif isinstance(
                    exam_date,
                    date
                ):

                    parsed_exam_date = (
                        exam_date
                    )

                else:

                    parsed_exam_date = (
                        date.fromisoformat(
                            str(
                                exam_date
                            )[:10]
                        )
                    )

                days_until_exam = max(
                    0,
                    (
                        parsed_exam_date
                        -
                        today
                    ).days
                )

            except (
                TypeError,
                ValueError
            ):

                days_until_exam = None

        subject_data[
            "days_until_exam"
        ] = days_until_exam

        display_subjects.append(
            subject_data
        )

    return render(
        request,
        "dashboard/goals.html",
        {
            "profile":
                profile,

            "subjects":
                display_subjects,

            "study_availability":
                study_availability,
        }
    )


# ============================================================
# STUDY SCHEDULE HELPERS
# ============================================================

def duration_to_minutes(value):

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


def format_study_minutes(
    total_minutes
):

    total_minutes = int(
        total_minutes
        or 0
    )

    hours = (
        total_minutes
        //
        60
    )

    minutes = (
        total_minutes
        %
        60
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


def get_availability_by_weekday(
    availability
):

    schedule = {

        0: {
            "name":
                "Monday",

            "enabled":
                False,

            "minutes":
                0,
        },

        1: {
            "name":
                "Tuesday",

            "enabled":
                False,

            "minutes":
                0,
        },

        2: {
            "name":
                "Wednesday",

            "enabled":
                False,

            "minutes":
                0,
        },

        3: {
            "name":
                "Thursday",

            "enabled":
                False,

            "minutes":
                0,
        },

        4: {
            "name":
                "Friday",

            "enabled":
                False,

            "minutes":
                0,
        },

        5: {
            "name":
                "Saturday",

            "enabled":
                False,

            "minutes":
                0,
        },

        6: {
            "name":
                "Sunday",

            "enabled":
                False,

            "minutes":
                0,
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
                duration_to_minutes(
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


# ============================================================
# SUBJECT DETAIL
# ============================================================

@login_required
def subject_detail(
    request,
    subject_index
):

    # ========================================================
    # PROFILE
    # ========================================================

    profile = request.session.get(
        "onboarding_profile"
    )

    if not profile:

        return redirect(
            "onboarding"
        )

    # ========================================================
    # SUBJECTS
    # ========================================================

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    # ========================================================
    # VALIDATE INDEX
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

    # ========================================================
    # CURRENT SUBJECT
    # ========================================================

    subject_data = subjects[
        subject_index
    ]

    subject_data.setdefault(
        "definitions",
        []
    )

    subject_data.setdefault(
        "formulas",
        []
    )

    subject_data.setdefault(
        "database_id",
        None
    )

    # ========================================================
    # CURRENT ACTION
    # ========================================================

    action = ""

    if (
        request.method
        ==
        "POST"
    ):

        action = request.POST.get(
            "action",
            ""
        )

    # ========================================================
    # DELETE SUBJECT
    # ========================================================

    if (
        request.method == "POST"
        and
        action == "delete_subject"
    ):

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

        if database_subject:

            database_subject.delete()

        subjects.pop(
            subject_index
        )

        profile[
            "subject_count"
        ] = len(
            subjects
        )

        request.session[
            "onboarding_subjects"
        ] = subjects

        request.session[
            "onboarding_profile"
        ] = profile

        request.session.modified = True

        return redirect(
            "goals"
        )

    # ========================================================
    # SAVE SUBJECT
    # ========================================================

    if (
        request.method == "POST"
        and
        action == "save_subject"
    ):

        subject_data[
            "name"
        ] = (
            request.POST.get(
                "name",
                ""
            )
            .strip()
        )

        subject_data[
            "target_grade"
        ] = request.POST.get(
            "target_grade",
            ""
        )

        subject_data[
            "exam_date"
        ] = request.POST.get(
            "exam_date",
            ""
        )

        subjects[
            subject_index
        ] = subject_data

        request.session[
            "onboarding_subjects"
        ] = subjects

        request.session.modified = True

    # ========================================================
    # FIND DATABASE SUBJECT
    # ========================================================

    database_subject = None

    database_subject_id = (
        subject_data.get(
            "database_id"
        )
    )

    # --------------------------------------------------------
    # DATABASE ID
    # --------------------------------------------------------

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
    # NAME FALLBACK
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

    # --------------------------------------------------------
    # CREATE DATABASE SUBJECT
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
                Subject.objects.create(
                    user=request.user,
                    name=subject_name,
                )
            )

    # ========================================================
    # UPDATE DATABASE SUBJECT NAME
    # ========================================================

    if database_subject:

        subject_name = (
            subject_data.get(
                "name",
                ""
            )
            .strip()
        )

        if (
            subject_name
            and
            database_subject.name
            !=
            subject_name
        ):

            database_subject.name = (
                subject_name
            )

            database_subject.save(
                update_fields=[
                    "name"
                ]
            )

    # ========================================================
    # SAVE DATABASE ID INTO SESSION
    # ========================================================

    if database_subject:

        if (
            subject_data.get(
                "database_id"
            )
            !=
            database_subject.id
        ):

            subject_data[
                "database_id"
            ] = database_subject.id

            subjects[
                subject_index
            ] = subject_data

            request.session[
                "onboarding_subjects"
            ] = subjects

            request.session.modified = True

    # ========================================================
    # NOTES
    #
    # This is the important new section.
    # It must be AFTER database_subject is resolved.
    # ========================================================

    if database_subject:

        notes = (
            Note.objects
            .filter(
                subject=database_subject
            )
            .order_by(
                "created",
                "id",
            )
        )

        note_count = (
            notes.count()
        )

    else:

        notes = (
            Note.objects.none()
        )

        note_count = 0

    # ========================================================
    # TODAY
    # ========================================================

    today = timezone.localdate()

    # ========================================================
    # EXAM
    # ========================================================

    days_until_exam = None
    study_days_before_revision = None
    study_days_left = None
    parsed_exam_date = None

    exam_date_value = (
        subject_data.get(
            "exam_date"
        )
    )

    # ========================================================
    # PARSE EXAM DATE
    # ========================================================

    if exam_date_value:

        try:

            if isinstance(
                exam_date_value,
                datetime
            ):

                parsed_exam_date = (
                    exam_date_value.date()
                )

            elif isinstance(
                exam_date_value,
                date
            ):

                parsed_exam_date = (
                    exam_date_value
                )

            else:

                parsed_exam_date = (
                    date.fromisoformat(
                        str(
                            exam_date_value
                        )[:10]
                    )
                )

        except (
            TypeError,
            ValueError
        ):

            parsed_exam_date = None

    # ========================================================
    # CALCULATE TOTAL STUDY DAYS BEFORE REVISION
    # ========================================================

    if (
        parsed_exam_date
        is not None
    ):

        days_until_exam = max(
            0,
            (
                parsed_exam_date
                -
                today
            ).days
        )

        availability = (
            StudyAvailability.objects
            .filter(
                user=request.user
            )
            .first()
        )

        enabled_weekdays = set()

        if availability:

            weekday_fields = [

                (
                    0,
                    "monday_enabled"
                ),

                (
                    1,
                    "tuesday_enabled"
                ),

                (
                    2,
                    "wednesday_enabled"
                ),

                (
                    3,
                    "thursday_enabled"
                ),

                (
                    4,
                    "friday_enabled"
                ),

                (
                    5,
                    "saturday_enabled"
                ),

                (
                    6,
                    "sunday_enabled"
                ),
            ]

            for (
                weekday_number,
                field_name
            ) in weekday_fields:

                if getattr(
                    availability,
                    field_name,
                    False
                ):

                    enabled_weekdays.add(
                        weekday_number
                    )

        study_days_before_revision = 0

        if (
            parsed_exam_date
            >
            today
        ):

            current_date = today

            while (
                current_date
                <
                parsed_exam_date
            ):

                if (
                    current_date.weekday()
                    in
                    enabled_weekdays
                ):

                    study_days_before_revision += 1

                current_date += timedelta(
                    days=1
                )

    # ========================================================
    # TEXTBOOK FORM VALUES / ERRORS
    # ========================================================

    textbook_error = None
    textbook_edit_error = None

    edit_textbook_id = ""
    edit_textbook_name = ""
    edit_textbook_pages = ""

    # ========================================================
    # ADD TEXTBOOK
    # ========================================================

    if (
        request.method == "POST"
        and
        action == "add_textbook"
    ):

        textbook_name = (
            request.POST.get(
                "textbook_name",
                ""
            )
            .strip()
        )

        page_count_raw = (
            request.POST.get(
                "page_count",
                ""
            )
            .strip()
        )

        page_count = None

        if not database_subject:

            textbook_error = (
                "Save the subject before "
                "adding a textbook."
            )

        elif not textbook_name:

            textbook_error = (
                "Please enter the textbook name."
            )

        else:

            try:

                page_count = int(
                    page_count_raw
                )

                if (
                    page_count
                    <=
                    0
                ):

                    raise ValueError

            except (
                TypeError,
                ValueError
            ):

                textbook_error = (
                    "Page count must be a whole "
                    "number greater than 0."
                )

        if (
            textbook_error
            is None
        ):

            SubjectTextbook.objects.create(
                subject=database_subject,
                name=textbook_name,
                page_count=page_count,
            )

            return redirect(
                "subject_detail",
                subject_index=subject_index,
            )

    # ========================================================
    # EDIT TEXTBOOK
    # ========================================================

    if (
        request.method == "POST"
        and
        action == "edit_textbook"
    ):

        textbook_id_raw = (
            request.POST.get(
                "textbook_id",
                ""
            )
            .strip()
        )

        textbook_name = (
            request.POST.get(
                "textbook_name",
                ""
            )
            .strip()
        )

        page_count_raw = (
            request.POST.get(
                "page_count",
                ""
            )
            .strip()
        )

        edit_textbook_id = (
            textbook_id_raw
        )

        edit_textbook_name = (
            textbook_name
        )

        edit_textbook_pages = (
            page_count_raw
        )

        textbook_to_edit = None
        page_count = None

        if not database_subject:

            textbook_edit_error = (
                "Could not find this subject."
            )

        else:

            try:

                textbook_id = int(
                    textbook_id_raw
                )

            except (
                TypeError,
                ValueError
            ):

                textbook_id = None

            if textbook_id:

                textbook_to_edit = (
                    SubjectTextbook.objects
                    .filter(
                        id=textbook_id,
                        subject=database_subject,
                    )
                    .first()
                )

            if not textbook_to_edit:

                textbook_edit_error = (
                    "Could not find that textbook."
                )

            elif not textbook_name:

                textbook_edit_error = (
                    "Please enter the textbook name."
                )

            else:

                try:

                    page_count = int(
                        page_count_raw
                    )

                    if (
                        page_count
                        <=
                        0
                    ):

                        raise ValueError

                except (
                    TypeError,
                    ValueError
                ):

                    textbook_edit_error = (
                        "Page count must be a whole "
                        "number greater than 0."
                    )

        if (
            textbook_edit_error
            is None
        ):

            textbook_to_edit.name = (
                textbook_name
            )

            textbook_to_edit.page_count = (
                page_count
            )

            textbook_to_edit.save(
                update_fields=[
                    "name",
                    "page_count",
                ]
            )

            return redirect(
                "subject_detail",
                subject_index=subject_index,
            )

    # ========================================================
    # DELETE TEXTBOOK
    # ========================================================

    if (
        request.method == "POST"
        and
        action == "delete_textbook"
    ):

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

        if (
            database_subject
            and
            textbook_id
        ):

            (
                SubjectTextbook.objects
                .filter(
                    id=textbook_id,
                    subject=database_subject,
                )
                .delete()
            )

        return redirect(
            "subject_detail",
            subject_index=subject_index,
        )

    # ========================================================
    # AUTOSAVE REVISION DAYS
    # ========================================================

    if (
        request.method == "POST"
        and
        action == "save_revision_days"
    ):

        if not database_subject:

            return JsonResponse(
                {
                    "success":
                        False,

                    "error":
                        (
                            "Save the subject before "
                            "setting revision days."
                        ),
                },
                status=400,
            )

        if (
            study_days_before_revision
            is None
        ):

            return JsonResponse(
                {
                    "success":
                        False,

                    "error":
                        (
                            "Set an exam date before "
                            "choosing revision days."
                        ),
                },
                status=400,
            )

        raw_revision_days = (
            request.POST.get(
                "revision_days",
                "0"
            )
            .strip()
        )

        try:

            revision_days_value = int(
                raw_revision_days
            )

        except (
            TypeError,
            ValueError
        ):

            return JsonResponse(
                {
                    "success":
                        False,

                    "error":
                        (
                            "Revision days must be "
                            "a whole number."
                        ),
                },
                status=400,
            )

        if (
            revision_days_value
            <
            0
        ):

            return JsonResponse(
                {
                    "success":
                        False,

                    "error":
                        (
                            "Revision days cannot "
                            "be negative."
                        ),
                },
                status=400,
            )

        if (
            revision_days_value
            >
            study_days_before_revision
        ):

            return JsonResponse(
                {
                    "success":
                        False,

                    "error":
                        (
                            f"You only have "
                            f"{study_days_before_revision} "
                            f"available study days "
                            f"before the exam."
                        ),
                },
                status=400,
            )

        revision_plan, created = (
            SubjectRevisionPlan.objects
            .get_or_create(
                subject=database_subject
            )
        )

        revision_plan.revision_days = (
            revision_days_value
        )

        revision_plan.save()

        true_study_days_left = max(
            0,
            (
                study_days_before_revision
                -
                revision_days_value
            )
        )

        if (
            request.headers.get(
                "X-Requested-With"
            )
            ==
            "XMLHttpRequest"
        ):

            return JsonResponse(
                {
                    "success":
                        True,

                    "revision_days":
                        revision_days_value,

                    "study_days_before_revision":
                        study_days_before_revision,

                    "study_days_left":
                        true_study_days_left,
                }
            )

        return redirect(
            "subject_detail",
            subject_index=subject_index,
        )

    # ========================================================
    # LOAD TEXTBOOKS
    # ========================================================

    textbooks = []

    total_textbook_pages = 0

    if database_subject:

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

        total_textbook_pages = sum(
            textbook.page_count

            for textbook
            in textbooks
        )

    # ========================================================
    # REVISION PLAN
    # ========================================================

    revision_plan = None
    revision_days = 0

    if database_subject:

        revision_plan = (
            SubjectRevisionPlan.objects
            .filter(
                subject=database_subject
            )
            .first()
        )

        if (
            revision_plan
            and
            revision_plan.revision_days
            is not None
        ):

            revision_days = (
                revision_plan.revision_days
            )

    # ========================================================
    # CAP REVISION DAYS
    # ========================================================

    if (
        study_days_before_revision
        is not None
        and
        revision_days
        >
        study_days_before_revision
    ):

        revision_days = (
            study_days_before_revision
        )

        if revision_plan:

            revision_plan.revision_days = (
                revision_days
            )

            revision_plan.save(
                update_fields=[
                    "revision_days"
                ]
            )

    # ========================================================
    # TRUE STUDY DAYS LEFT
    # ========================================================

    if (
        study_days_before_revision
        is not None
    ):

        study_days_left = max(
            0,
            (
                study_days_before_revision
                -
                revision_days
            )
        )

    else:

        study_days_left = None

    # ========================================================
    # PAGES TO SUMMARIZE TODAY
    # ========================================================

    pages_to_summarize = []

    pages_to_summarize_total = 0

    pages_today_weekday = (
        today.strftime(
            "%A"
        )
    )

    pages_today_weekday_count = 0

    pages_today_study_time = ""

    pages_today_weekday_total_time = ""

    pages_total_learning_time = ""

    pages_today_weekday_percentage = 0

    today_is_learning_day = False

    if (
        parsed_exam_date is not None
        and
        parsed_exam_date > today
        and
        database_subject
        and
        textbooks
    ):

        page_availability = (
            StudyAvailability.objects
            .filter(
                user=request.user
            )
            .first()
        )

        weekday_schedule = (
            get_availability_by_weekday(
                page_availability
            )
        )

        # ====================================================
        # BUILD REMAINING STUDY DATES
        # ====================================================

        remaining_study_dates = []

        current_date = today

        while (
            current_date
            <
            parsed_exam_date
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

        # ====================================================
        # REMOVE REVISION DAYS
        # ====================================================

        revision_days_for_schedule = int(
            revision_days
            or
            0
        )

        revision_days_for_schedule = max(
            0,
            min(
                revision_days_for_schedule,
                len(
                    remaining_study_dates
                )
            )
        )

        if (
            revision_days_for_schedule
            >
            0
        ):

            learning_dates = (
                remaining_study_dates[
                    :-revision_days_for_schedule
                ]
            )

        else:

            learning_dates = list(
                remaining_study_dates
            )

        # ====================================================
        # REMOVE ZERO-TIME DAYS
        # ====================================================

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

            if (
                minutes
                >
                0
            ):

                learning_dates_with_time.append(
                    learning_date
                )

        weekday_counts = Counter(
            learning_date.weekday()

            for learning_date
            in learning_dates_with_time
        )

        total_learning_minutes = sum(

            weekday_schedule[
                learning_date.weekday()
            ][
                "minutes"
            ]

            for learning_date
            in learning_dates_with_time
        )

        pages_total_learning_time = (
            format_study_minutes(
                total_learning_minutes
            )
        )

        today_weekday = (
            today.weekday()
        )

        today_minutes = (
            weekday_schedule[
                today_weekday
            ][
                "minutes"
            ]
        )

        pages_today_study_time = (
            format_study_minutes(
                today_minutes
            )
        )

        if (
            today
            in
            learning_dates_with_time
            and
            total_learning_minutes > 0
            and
            today_minutes > 0
        ):

            today_is_learning_day = True

            pages_today_weekday_count = (
                weekday_counts.get(
                    today_weekday,
                    0
                )
            )

            weekday_total_minutes = (
                pages_today_weekday_count
                *
                today_minutes
            )

            pages_today_weekday_total_time = (
                format_study_minutes(
                    weekday_total_minutes
                )
            )

            pages_today_weekday_percentage = (
                round(
                    (
                        weekday_total_minutes
                        /
                        total_learning_minutes
                    )
                    *
                    100,
                    2,
                )
            )

            for textbook in textbooks:

                remaining_pages = max(
                    0,
                    (
                        textbook.page_count
                        -
                        textbook.pages_summarized
                    )
                )

                if (
                    remaining_pages
                    <=
                    0
                ):

                    continue

                if (
                    textbook.last_summary_date
                    ==
                    today
                ):

                    continue

                weekday_pages_exact = (
                    remaining_pages
                    *
                    (
                        weekday_total_minutes
                        /
                        total_learning_minutes
                    )
                )

                if (
                    pages_today_weekday_count
                    >
                    0
                ):

                    pages_today_exact = (
                        weekday_pages_exact
                        /
                        pages_today_weekday_count
                    )

                else:

                    pages_today_exact = 0

                if (
                    pages_today_exact
                    >
                    0
                ):

                    pages_today = int(
                        pages_today_exact
                        +
                        0.5
                    )

                    pages_today = max(
                        1,
                        pages_today
                    )

                    pages_today = min(
                        pages_today,
                        remaining_pages
                    )

                else:

                    pages_today = 0

                if (
                    pages_today
                    >
                    0
                ):

                    pages_to_summarize.append(
                        {
                            "textbook":
                                textbook,

                            "pages":
                                pages_today,

                            "exact_pages":
                                round(
                                    pages_today_exact,
                                    2
                                ),

                            "weekday_pages":
                                round(
                                    weekday_pages_exact,
                                    2
                                ),
                        }
                    )

                    pages_to_summarize_total += (
                        pages_today
                    )

    # ========================================================
    # REVIEW ITEMS
    # ========================================================

    due_formulas = []
    due_definitions = []
    due_bullet_lists = []
    due_step_lists = []

    # ========================================================
    # FIND DUE ITEMS
    # ========================================================

    if database_subject:

        # ====================================================
        # FORMULAS
        # ====================================================

        formula_knowledge_units = (
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

        for knowledge_unit in (
            formula_knowledge_units
        ):

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
                    knowledge_unit=knowledge_unit,
                )
                .first()
            )

            is_due = False

            if progress is None:

                is_due = True

            elif progress.next_review is None:

                is_due = True

            else:

                next_review_date = (
                    timezone.localtime(
                        progress.next_review
                    )
                    .date()
                )

                if (
                    next_review_date
                    <=
                    today
                ):

                    is_due = True

            if is_due:

                due_formulas.append(
                    formula
                )

        # ====================================================
        # DEFINITIONS
        # ====================================================

        definition_knowledge_units = (
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

        for knowledge_unit in (
            definition_knowledge_units
        ):

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
                    knowledge_unit=knowledge_unit,
                )
                .first()
            )

            is_due = False

            if progress is None:

                is_due = True

            elif progress.next_review is None:

                is_due = True

            else:

                next_review_date = (
                    timezone.localtime(
                        progress.next_review
                    )
                    .date()
                )

                if (
                    next_review_date
                    <=
                    today
                ):

                    is_due = True

            if is_due:

                due_definitions.append(
                    definition
                )

        # ====================================================
        # LISTS
        # ====================================================

        bullet_lists = (
            BulletList.objects
            .filter(
                knowledge_unit__subject=database_subject,
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
                        bullet_list
                        .knowledge_unit
                    ),
                )
                .first()
            )

            is_due = False

            if progress is None:

                is_due = True

            elif progress.next_review is None:

                is_due = True

            else:

                next_review_date = (
                    timezone.localtime(
                        progress.next_review
                    )
                    .date()
                )

                if (
                    next_review_date
                    <=
                    today
                ):

                    is_due = True

            if is_due:

                due_bullet_lists.append(
                    bullet_list
                )

        # ====================================================
        # STEPS
        # ====================================================

        step_lists = (
            StepList.objects
            .filter(
                knowledge_unit__subject=database_subject,
                knowledge_unit__active=True,
            )
            .select_related(
                "knowledge_unit",
                "knowledge_unit__subject",
            )
            .prefetch_related(
                "steps"
            )
            .order_by(
                "knowledge_unit__created",
                "id",
            )
        )

        for step_list in (
            step_lists
        ):

            knowledge_unit = (
                step_list.knowledge_unit
            )

            progress = (
                StudentKnowledge.objects
                .filter(
                    student=request.user,
                    knowledge_unit=knowledge_unit,
                )
                .first()
            )

            is_due = False

            if progress is None:

                is_due = True

            elif progress.next_review is None:

                is_due = True

            else:

                next_review_date = (
                    timezone.localtime(
                        progress.next_review
                    )
                    .date()
                )

                if (
                    next_review_date
                    <=
                    today
                ):

                    is_due = True

            if is_due:

                due_step_lists.append(
                    step_list
                )

    # ========================================================
    # COUNTS
    # ========================================================

    due_formula_count = len(
        due_formulas
    )

    due_definition_count = len(
        due_definitions
    )

    due_bullet_list_count = len(
        due_bullet_lists
    )

    due_step_list_count = len(
        due_step_lists
    )

    total_due_reviews = (
        due_formula_count
        +
        due_definition_count
        +
        due_bullet_list_count
        +
        due_step_list_count
    )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "dashboard/subject_detail.html",
        {
            # --------------------------------------------
            # SUBJECT
            # --------------------------------------------

            "profile":
                profile,

            "subject":
                subject_data,

            "subject_index":
                subject_index,

            "database_subject":
                database_subject,

            "subject_id":
                (
                    database_subject.id
                    if database_subject
                    else None
                ),

            # --------------------------------------------
            # NOTES
            # --------------------------------------------

            "notes":
                notes,

            "note_count":
                note_count,

            # --------------------------------------------
            # TEXTBOOKS
            # --------------------------------------------

            "textbooks":
                textbooks,

            "total_textbook_pages":
                total_textbook_pages,

            "textbook_error":
                textbook_error,

            "textbook_edit_error":
                textbook_edit_error,

            "edit_textbook_id":
                edit_textbook_id,

            "edit_textbook_name":
                edit_textbook_name,

            "edit_textbook_pages":
                edit_textbook_pages,

            # --------------------------------------------
            # REVISION
            # --------------------------------------------

            "revision_days":
                revision_days,

            # --------------------------------------------
            # COUNTDOWN
            # --------------------------------------------

            "days_until_exam":
                days_until_exam,

            "study_days_before_revision":
                study_days_before_revision,

            "study_days_left":
                study_days_left,

            # --------------------------------------------
            # PAGES TO SUMMARIZE
            # --------------------------------------------

            "pages_to_summarize":
                pages_to_summarize,

            "pages_to_summarize_total":
                pages_to_summarize_total,

            "pages_today_weekday":
                pages_today_weekday,

            "pages_today_weekday_count":
                pages_today_weekday_count,

            "pages_today_study_time":
                pages_today_study_time,

            "pages_today_weekday_total_time":
                pages_today_weekday_total_time,

            "pages_total_learning_time":
                pages_total_learning_time,

            "pages_today_weekday_percentage":
                pages_today_weekday_percentage,

            "today_is_learning_day":
                today_is_learning_day,

            # --------------------------------------------
            # REVIEWS
            # --------------------------------------------

            "due_formulas":
                due_formulas,

            "due_formula_count":
                due_formula_count,

            "due_definitions":
                due_definitions,

            "due_definition_count":
                due_definition_count,

            "due_bullet_lists":
                due_bullet_lists,

            "due_bullet_list_count":
                due_bullet_list_count,

            "due_step_lists":
                due_step_lists,

            "due_step_list_count":
                due_step_list_count,

            "total_due_reviews":
                total_due_reviews,
        }
    )


# ============================================================
# DEFINITIONS
# ============================================================

@login_required
def definition(
    request,
    subject_index
):

    profile = request.session.get(
        "onboarding_profile"
    )

    if not profile:

        return redirect(
            "onboarding"
        )

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
        or
        subject_index >= len(
            subjects
        )
    ):

        return redirect(
            "goals"
        )

    subject_data = subjects[
        subject_index
    ]

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
                user=request.user
            )
            .first()
        )

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
                    name=subject_name
                )
                .first()
            )

    # --------------------------------------------------------
    # SAVE DEFINITION
    # --------------------------------------------------------

    if request.method == "POST":

        term = (
            request.POST.get(
                "term",
                ""
            )
            .strip()
        )

        meaning = (
            request.POST.get(
                "meaning",
                ""
            )
            .strip()
        )

        if (
            term
            and
            meaning
            and
            database_subject
        ):

            knowledge_unit = (
                KnowledgeUnit.objects.create(
                    subject=database_subject,
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
            )

            Definition.objects.create(
                knowledge_unit=knowledge_unit,
                term=term,
                definition=meaning,
            )

        return redirect(
            "definition",
            subject_index=subject_index
        )

    # --------------------------------------------------------
    # DEFINITIONS
    # --------------------------------------------------------

    definitions = []

    if database_subject:

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
            .order_by(
                "-created"
            )
        )

        definitions = [

            knowledge_unit.definition

            for knowledge_unit
            in knowledge_units

            if hasattr(
                knowledge_unit,
                "definition"
            )
        ]

    return render(
        request,
        "dashboard/definition.html",
        {
            "subject":
                subject_data,

            "subject_index":
                subject_index,

            "definitions":
                definitions,
        }
    )


# ============================================================
# REVIEW DEFINITIONS
# ============================================================

@login_required
def review_definitions(request):

    definition_knowledge_units = (
        KnowledgeUnit.objects
        .filter(
            subject__user=request.user,
            knowledge_type=(
                KnowledgeUnit
                .KnowledgeType
                .DEFINITION
            ),
            active=True,
        )
        .select_related(
            "definition",
            "subject",
        )
        .order_by(
            "subject__name",
            "definition__term",
        )
    )

    definitions = []

    for knowledge_unit in (
        definition_knowledge_units
    ):

        definition = getattr(
            knowledge_unit,
            "definition",
            None
        )

        if definition:

            definitions.append(
                {
                    "definition":
                        definition,

                    "subject":
                        knowledge_unit.subject,
                }
            )

    return render(
        request,
        "dashboard/review_definitions.html",
        {
            "definitions":
                definitions,

            "definition_count":
                len(
                    definitions
                ),
        }
    )


# ============================================================
# REVIEW FORMULAS
# ============================================================

@login_required
def review_formulas(request):

    formulas = (
        Formula.objects
        .filter(
            knowledge_unit__subject__user=request.user,
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
            "knowledge_unit__subject__name",
            "knowledge_unit__title",
            "id",
        )
    )

    formula_items = []

    for formula in formulas:

        formula_items.append(
            {
                "formula":
                    formula,

                "subject":
                    formula.knowledge_unit.subject,

                "knowledge_unit":
                    formula.knowledge_unit,
            }
        )

    return render(
        request,
        "dashboard/review_formulas.html",
        {
            "formulas":
                formula_items,

            "formula_count":
                len(
                    formula_items
                ),
        }
    )


# ============================================================
# REVIEW LISTS
# ============================================================

@login_required
def review_lists(request):

    bullet_lists = (
        BulletList.objects
        .filter(
            knowledge_unit__subject__user=request.user,
            knowledge_unit__active=True,
        )
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        )
        .prefetch_related(
            "items"
        )
        .order_by(
            "knowledge_unit__subject__name",
            "knowledge_unit__created",
            "id",
        )
    )

    list_items = []

    for bullet_list in bullet_lists:

        list_items.append(
            {
                "list":
                    bullet_list,

                "subject":
                    bullet_list
                    .knowledge_unit
                    .subject,

                "knowledge_unit":
                    bullet_list
                    .knowledge_unit,
            }
        )

    return render(
        request,
        "dashboard/review_lists.html",
        {
            "lists":
                list_items,

            "list_count":
                len(
                    list_items
                ),
        }
    )


# ============================================================
# REVIEW STEPS
# ============================================================

@login_required
def review_steps(request):

    step_lists = (
        StepList.objects
        .filter(
            knowledge_unit__subject__user=request.user,
            knowledge_unit__active=True,
        )
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        )
        .prefetch_related(
            "steps"
        )
        .order_by(
            "knowledge_unit__subject__name",
            "knowledge_unit__created",
            "id",
        )
    )

    step_items = []

    for step_list in step_lists:

        step_items.append(
            {
                "step_list":
                    step_list,

                "subject":
                    step_list
                    .knowledge_unit
                    .subject,

                "knowledge_unit":
                    step_list
                    .knowledge_unit,
            }
        )

    return render(
        request,
        "dashboard/review_steps.html",
        {
            "steps":
                step_items,

            "step_count":
                len(
                    step_items
                ),
        }
    )


# ============================================================
# REVIEW NOTES
# ============================================================

@login_required
def review_notes(request):

    # ========================================================
    # ALL NOTES FOR THIS USER
    # ========================================================

    notes = (
        Note.objects
        .filter(
            subject__user=request.user
        )
        .select_related(
            "subject"
        )
        .order_by(
            "subject__name",
            "created",
            "id",
        )
    )

    # ========================================================
    # BUILD TEMPLATE ITEMS
    # ========================================================

    note_items = []

    for note in notes:

        note_items.append(
            {
                "note":
                    note,

                "subject":
                    note.subject,
            }
        )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "dashboard/review_notes.html",
        {
            "notes":
                note_items,

            "note_count":
                len(
                    note_items
                ),
        }
    )

# ============================================================
# PROGRESS
# ============================================================

@login_required
def progress(request):

    # ========================================================
    # SUBJECTS
    # ========================================================

    subjects = (
        Subject.objects
        .filter(
            user=request.user
        )
        .order_by(
            "name"
        )
    )

    # ========================================================
    # KNOWLEDGE UNITS
    # ========================================================

    knowledge_units = (
        KnowledgeUnit.objects
        .filter(
            subject__user=request.user,
            active=True,
        )
        .select_related(
            "subject",
        )
    )

    # ========================================================
    # KNOWLEDGE PROGRESS RECORDS
    # ========================================================

    progress_records = (
        StudentKnowledge.objects
        .filter(
            student=request.user,
            knowledge_unit__in=knowledge_units,
        )
        .select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        )
    )

    # ========================================================
    # TEXTBOOKS
    # ========================================================

    textbooks = list(
        SubjectTextbook.objects
        .filter(
            subject__user=request.user
        )
        .select_related(
            "subject"
        )
        .order_by(
            "subject__name",
            "created",
            "id",
        )
    )

    # ========================================================
    # OVERALL KNOWLEDGE STATISTICS
    # ========================================================

    total_knowledge = (
        knowledge_units.count()
    )

    reviewed_count = (
        progress_records.count()
    )

    mastered_count = (
        progress_records
        .filter(
            mastery_level__gte=6
        )
        .count()
    )

    total_correct = sum(
        record.correct_count
        for record
        in progress_records
    )

    total_incorrect = sum(
        record.incorrect_count
        for record
        in progress_records
    )

    total_reviews = (
        total_correct
        +
        total_incorrect
    )

    # --------------------------------------------------------
    # ACCURACY
    # --------------------------------------------------------

    if total_reviews > 0:

        accuracy = round(
            (
                total_correct
                /
                total_reviews
            )
            *
            100
        )

    else:

        accuracy = 0

    # --------------------------------------------------------
    # OVERALL MASTERY
    # --------------------------------------------------------

    if total_knowledge > 0:

        overall_mastery = round(
            (
                mastered_count
                /
                total_knowledge
            )
            *
            100
        )

    else:

        overall_mastery = 0

    # ========================================================
    # OVERALL TEXTBOOK PAGE PROGRESS
    # ========================================================

    total_textbook_pages = sum(
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
            total_textbook_pages
            -
            total_pages_summarized
        )
    )

    if total_textbook_pages > 0:

        overall_page_progress = round(
            (
                total_pages_summarized
                /
                total_textbook_pages
            )
            *
            100,
            1,
        )

    else:

        overall_page_progress = 0

    # ========================================================
    # GROUP TEXTBOOKS BY SUBJECT
    # ========================================================

    textbooks_by_subject = {}

    for textbook in textbooks:

        subject_id = (
            textbook.subject_id
        )

        if (
            subject_id
            not in
            textbooks_by_subject
        ):

            textbooks_by_subject[
                subject_id
            ] = []

        textbooks_by_subject[
            subject_id
        ].append(
            textbook
        )

    # ========================================================
    # SUBJECT PROGRESS
    # ========================================================

    subject_progress = []

    for subject in subjects:

        subject_units = (
            knowledge_units
            .filter(
                subject=subject
            )
        )

        subject_unit_count = (
            subject_units.count()
        )

        subject_progress_records = (
            progress_records
            .filter(
                knowledge_unit__subject=subject
            )
        )

        subject_textbooks = (
            textbooks_by_subject.get(
                subject.id,
                []
            )
        )

        if (
            subject_unit_count == 0
            and
            not subject_textbooks
        ):

            continue

        # ====================================================
        # KNOWLEDGE MASTERY
        # ====================================================

        subject_mastered = (
            subject_progress_records
            .filter(
                mastery_level__gte=6
            )
            .count()
        )

        subject_reviews = sum(
            record.review_count
            for record
            in subject_progress_records
        )

        subject_correct = sum(
            record.correct_count
            for record
            in subject_progress_records
        )

        subject_incorrect = sum(
            record.incorrect_count
            for record
            in subject_progress_records
        )

        subject_total_answers = (
            subject_correct
            +
            subject_incorrect
        )

        if subject_total_answers > 0:

            subject_accuracy = round(
                (
                    subject_correct
                    /
                    subject_total_answers
                )
                *
                100
            )

        else:

            subject_accuracy = 0

        if subject_unit_count > 0:

            subject_mastery = round(
                (
                    subject_mastered
                    /
                    subject_unit_count
                )
                *
                100
            )

        else:

            subject_mastery = 0

        # ====================================================
        # SUBJECT PAGE PROGRESS
        # ====================================================

        subject_total_pages = sum(
            textbook.page_count
            for textbook
            in subject_textbooks
        )

        subject_pages_summarized = sum(
            min(
                textbook.pages_summarized,
                textbook.page_count
            )
            for textbook
            in subject_textbooks
        )

        subject_pages_remaining = max(
            0,
            (
                subject_total_pages
                -
                subject_pages_summarized
            )
        )

        if subject_total_pages > 0:

            subject_page_progress = round(
                (
                    subject_pages_summarized
                    /
                    subject_total_pages
                )
                *
                100,
                1,
            )

        else:

            subject_page_progress = 0

        subject_progress.append(
            {
                "subject":
                    subject,

                "total_units":
                    subject_unit_count,

                "reviewed":
                    subject_progress_records.count(),

                "mastered":
                    subject_mastered,

                "reviews":
                    subject_reviews,

                "correct":
                    subject_correct,

                "incorrect":
                    subject_incorrect,

                "accuracy":
                    subject_accuracy,

                "mastery":
                    subject_mastery,

                "textbook_count":
                    len(
                        subject_textbooks
                    ),

                "total_pages":
                    subject_total_pages,

                "pages_summarized":
                    subject_pages_summarized,

                "pages_remaining":
                    subject_pages_remaining,

                "page_progress":
                    subject_page_progress,
            }
        )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "dashboard/progress.html",
        {
            "total_knowledge":
                total_knowledge,

            "reviewed_count":
                reviewed_count,

            "mastered_count":
                mastered_count,

            "total_correct":
                total_correct,

            "total_incorrect":
                total_incorrect,

            "total_reviews":
                total_reviews,

            "accuracy":
                accuracy,

            "overall_mastery":
                overall_mastery,

            "total_textbook_pages":
                total_textbook_pages,

            "total_pages_summarized":
                total_pages_summarized,

            "total_pages_remaining":
                total_pages_remaining,

            "overall_page_progress":
                overall_page_progress,

            "subject_progress":
                subject_progress,
        }
    )
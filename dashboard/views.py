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
    StudentKnowledge,
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

            elif (
                progress.next_review.date()
                <= today
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
            # FIND SUBJECT INDEX
            # ------------------------------------------------

            subject_index = None

            # --------------------------------------------
            # DATABASE ID
            # --------------------------------------------

            for index, subject_data in enumerate(
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
                    == database_subject.id
                ):

                    subject_index = index

                    break

            # --------------------------------------------
            # FALLBACK TO NAME
            # --------------------------------------------

            if subject_index is None:

                for index, subject_data in enumerate(
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
                        == database_subject.name.strip()
                    ):

                        subject_index = index

                        break

            # --------------------------------------------
            # SKIP IF CANNOT FIND SESSION SUBJECT
            # --------------------------------------------

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
                not in definition_groups
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

        # ----------------------------------------------------
        # FINAL DEFINITION LIST
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # CHECK EACH FORMULA
        # ----------------------------------------------------

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

            elif (
                progress.next_review.date()
                <= today
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
            # FIND SUBJECT INDEX
            # ------------------------------------------------

            subject_index = None

            # --------------------------------------------
            # DATABASE ID
            # --------------------------------------------

            for index, subject_data in enumerate(
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
                    == database_subject.id
                ):

                    subject_index = index

                    break

            # --------------------------------------------
            # FALLBACK TO NAME
            # --------------------------------------------

            if subject_index is None:

                for index, subject_data in enumerate(
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
                        == database_subject.name.strip()
                    ):

                        subject_index = index

                        break

            # --------------------------------------------
            # SKIP IF NOT FOUND
            # --------------------------------------------

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
                not in formula_groups
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

        # ----------------------------------------------------
        # FINAL FORMULA LIST
        # ----------------------------------------------------

        due_formula_subjects = list(
            formula_groups.values()
        )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "dashboard/dashboard.html",
        {
            "onboarding_complete":
                onboarding_complete,

            "due_definition_subjects":
                due_definition_subjects,

            "due_definition_total":
                due_definition_total,

            "due_formula_subjects":
                due_formula_subjects,

            "due_formula_total":
                due_formula_total,
        }
    )


# ============================================================
# REVIEW
# ============================================================

@login_required
def review(request):

    # --------------------------------------------------------
    # GET ALL SUBJECTS FOR THIS STUDENT
    # --------------------------------------------------------

    subjects = Subject.objects.filter(
        user=request.user
    )

    # --------------------------------------------------------
    # GET ALL DEFINITIONS
    # --------------------------------------------------------

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

    for knowledge_unit in definition_knowledge_units:

        definition = getattr(
            knowledge_unit,
            "definition",
            None
        )

        if definition:

            definitions.append(
                definition
            )

    # --------------------------------------------------------
    # GET ALL FORMULAS
    # --------------------------------------------------------

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

    for knowledge_unit in formula_knowledge_units:

        formula = getattr(
            knowledge_unit,
            "formula",
            None
        )

        if formula:

            formulas.append(
                formula
            )

    # --------------------------------------------------------
    # COUNTS
    # --------------------------------------------------------

    definition_count = len(
        definitions
    )

    formula_count = len(
        formulas
    )

    # --------------------------------------------------------
    # RENDER
    # --------------------------------------------------------

    return render(
        request,
        "dashboard/review.html",
        {
            "subjects":
                subjects,

            "definitions":
                definitions,

            "definition_count":
                definition_count,

            "formulas":
                formulas,

            "formula_count":
                formula_count,
        }
    )


# ============================================================
# ONBOARDING
# ============================================================

@login_required
def onboarding(request):

    if request.method == "POST":

        workspace_name = request.POST.get(
            "workspace_name",
            ""
        ).strip()

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

        # ----------------------------------------------------
        # NEVER ALLOW MORE THAN 20 SUBJECTS
        # ----------------------------------------------------

        subject_count = max(
            1,
            min(
                subject_count,
                20
            )
        )

        # ----------------------------------------------------
        # SAVE PROFILE
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # CREATE EMPTY SUBJECT SLOTS
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # MARK ONBOARDING AS COMPLETE
        # ----------------------------------------------------

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

    # --------------------------------------------------------
    # PROFILE
    # --------------------------------------------------------

    profile = request.session.get(
        "onboarding_profile"
    )

    if not profile:

        return redirect(
            "onboarding"
        )

    # --------------------------------------------------------
    # SUBJECTS
    # --------------------------------------------------------

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    # --------------------------------------------------------
    # DAYS
    # --------------------------------------------------------

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
    # GET OR CREATE STUDY AVAILABILITY
    # ========================================================

    availability_record, created = (
        StudyAvailability.objects
        .get_or_create(
            user=request.user
        )
    )

    # ========================================================
    # BUILD TEMPLATE AVAILABILITY
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
        # LEGACY TARGET ACTION
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
        # AUTOSAVE STUDY AVAILABILITY
        # ====================================================

        elif action == "update_availability":

            errors = {}

            for day in days:

                enabled = (
                    request.POST.get(
                        f"{day}_enabled",
                        "0"
                    )
                    == "1"
                )

                raw_time = (
                    request.POST.get(
                        f"{day}_time",
                        ""
                    )
                    .strip()
                )

                # --------------------------------------------
                # DISABLED DAY
                # --------------------------------------------

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

                # --------------------------------------------
                # ENABLE DAY
                # --------------------------------------------

                setattr(
                    availability_record,
                    f"{day}_enabled",
                    True
                )

                # --------------------------------------------
                # ENABLED BUT TIME NOT ENTERED YET
                # --------------------------------------------

                if raw_time == "":

                    setattr(
                        availability_record,
                        f"{day}_time",
                        ""
                    )

                    continue

                # --------------------------------------------
                # VALIDATE HH:MM
                # --------------------------------------------

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

            # =================================================
            # INVALID
            # =================================================

            if errors:

                return JsonResponse(
                    {
                        "success": False,
                        "errors": errors,
                    },
                    status=400,
                )

            # =================================================
            # SAVE DATABASE
            # =================================================

            availability_record.save()

            if (
                request.headers.get(
                    "X-Requested-With"
                )
                == "XMLHttpRequest"
            ):

                return JsonResponse(
                    {
                        "success": True,
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
                - 1
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
    # DAYS UNTIL EXAM FOR GOALS CARDS
    # ========================================================

    today = timezone.localdate()

    display_subjects = []

    for subject in subjects:

        subject_data = dict(
            subject
        )

        exam_date = subject_data.get(
            "exam_date"
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
                        - today
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

    # ========================================================
    # RENDER
    # ========================================================

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
# SUBJECT DETAIL
# ============================================================

@login_required
def subject_detail(
    request,
    subject_index
):

    # --------------------------------------------------------
    # PROFILE
    # --------------------------------------------------------

    profile = request.session.get(
        "onboarding_profile"
    )

    if not profile:

        return redirect(
            "onboarding"
        )

    # --------------------------------------------------------
    # SUBJECTS
    # --------------------------------------------------------

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    # --------------------------------------------------------
    # VALIDATE INDEX
    # --------------------------------------------------------

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
        subject_index >= len(subjects)
    ):

        return redirect(
            "goals"
        )

    # --------------------------------------------------------
    # CURRENT SUBJECT
    # --------------------------------------------------------

    subject_data = subjects[
        subject_index
    ]

    # --------------------------------------------------------
    # REQUIRED FIELDS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # CURRENT ACTION
    # --------------------------------------------------------

    action = ""

    if request.method == "POST":

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

        # ----------------------------------------------------
        # FIND BY DATABASE ID
        # ----------------------------------------------------

        if database_subject_id:

            database_subject = (
                Subject.objects
                .filter(
                    id=database_subject_id,
                    user=request.user,
                )
                .first()
            )

        # ----------------------------------------------------
        # FALLBACK TO NAME
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # DELETE DATABASE SUBJECT
        # ----------------------------------------------------

        if database_subject:

            database_subject.delete()

        # ----------------------------------------------------
        # DELETE SESSION SUBJECT
        # ----------------------------------------------------

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
    # SAVE SUBJECT INFORMATION
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
    # FALLBACK TO NAME
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

    # --------------------------------------------------------
    # SYNCHRONIZE DATABASE NAME
    # --------------------------------------------------------

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
            != subject_name
        ):

            database_subject.name = (
                subject_name
            )

            database_subject.save(
                update_fields=[
                    "name"
                ]
            )

    # --------------------------------------------------------
    # SAVE DATABASE ID INTO SESSION
    # --------------------------------------------------------

    if database_subject:

        if (
            subject_data.get(
                "database_id"
            )
            != database_subject.id
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
    # TODAY
    # ========================================================

    today = timezone.localdate()

    # ========================================================
    # EXAM COUNTDOWN
    # ========================================================

    days_until_exam = None

    study_days_left = None

    parsed_exam_date = None

    exam_date_value = (
        subject_data.get(
            "exam_date"
        )
    )

    # --------------------------------------------------------
    # PARSE EXAM DATE
    # --------------------------------------------------------

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
    # CALCULATE DAYS
    # ========================================================

    if parsed_exam_date is not None:

        # ----------------------------------------------------
        # CALENDAR DAYS
        # ----------------------------------------------------

        days_until_exam = max(
            0,
            (
                parsed_exam_date
                - today
            ).days
        )

        # ----------------------------------------------------
        # STUDY AVAILABILITY
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # COUNT STUDY DAYS
        #
        # Today counts if selected.
        # Exam day does not count.
        # ----------------------------------------------------

        study_days_left = 0

        if (
            parsed_exam_date
            > today
        ):

            current_date = today

            while (
                current_date
                < parsed_exam_date
            ):

                if (
                    current_date.weekday()
                    in enabled_weekdays
                ):

                    study_days_left += 1

                current_date += timedelta(
                    days=1
                )

    # ========================================================
    # FORM ERRORS
    # ========================================================

    textbook_error = None

    revision_error = None

    revision_form_attempted = False

    revision_input_value = ""

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

        # ----------------------------------------------------
        # SUBJECT MUST EXIST
        # ----------------------------------------------------

        if not database_subject:

            textbook_error = (
                "Save the subject before adding a textbook."
            )

        # ----------------------------------------------------
        # NAME REQUIRED
        # ----------------------------------------------------

        elif not textbook_name:

            textbook_error = (
                "Please enter the textbook name."
            )

        else:

            try:

                page_count = int(
                    page_count_raw
                )

                if page_count <= 0:

                    raise ValueError

            except (
                TypeError,
                ValueError
            ):

                textbook_error = (
                    "Page count must be a whole number "
                    "greater than 0."
                )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        if textbook_error is None:

            SubjectTextbook.objects.create(
                subject=database_subject,
                name=textbook_name,
                page_count=page_count,
            )

            return redirect(
                "subject_detail",
                subject_index=subject_index
            )


    # ========================================================
    # AUTOSAVE REVISION DAYS
    # ========================================================

    if (
        request.method == "POST"
        and
        action == "save_revision_days"
    ):

        # ----------------------------------------------------
        # SUBJECT MUST EXIST
        # ----------------------------------------------------

        if not database_subject:

            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "Save the subject before "
                        "setting revision days."
                    ),
                },
                status=400,
            )

        # ----------------------------------------------------
        # EXAM DATE MUST EXIST
        # ----------------------------------------------------

        if study_days_left is None:

            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "Set an exam date before "
                        "choosing revision days."
                    ),
                },
                status=400,
            )

        # ----------------------------------------------------
        # GET VALUE
        # ----------------------------------------------------

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
                    "success": False,
                    "error": (
                        "Revision days must be "
                        "a whole number."
                    ),
                },
                status=400,
            )

        # ----------------------------------------------------
        # MINIMUM
        # ----------------------------------------------------

        if revision_days_value < 0:

            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "Revision days cannot "
                        "be negative."
                    ),
                },
                status=400,
            )

        # ----------------------------------------------------
        # MAXIMUM
        # ----------------------------------------------------

        if (
            revision_days_value
            > study_days_left
        ):

            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        f"You only have "
                        f"{study_days_left} "
                        f"study days left."
                    ),
                },
                status=400,
            )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # AJAX RESPONSE
        # ----------------------------------------------------

        if (
            request.headers.get(
                "X-Requested-With"
            )
            == "XMLHttpRequest"
        ):

            return JsonResponse(
                {
                    "success": True,
                    "revision_days":
                        revision_days_value,

                    "study_days_left":
                        study_days_left,
                }
            )

        return redirect(
            "subject_detail",
            subject_index=subject_index
        )


    # ========================================================
    # TEXTBOOKS
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
    # AUTOMATICALLY CAP REVISION DAYS
    #
    # Example:
    # Student originally had 15 study days left and chose
    # 10 revision days.
    #
    # Later their availability changes and they now only
    # have 8 study days left.
    #
    # Revision days automatically becomes 8.
    # ========================================================

    if (
        study_days_left is not None
        and
        revision_days
        > study_days_left
    ):

        revision_days = (
            study_days_left
        )


        if revision_plan:

            revision_plan.revision_days = (
                revision_days
            )

            revision_plan.save()

    # --------------------------------------------------------
    # VALUE DISPLAYED IN INPUT
    # --------------------------------------------------------

    if not revision_form_attempted:

        if revision_days is None:

            revision_input_value = ""

        else:

            revision_input_value = str(
                revision_days
            )

    # ========================================================
    # REVIEW LISTS
    # ========================================================

    due_formulas = []

    due_definitions = []

    due_bullet_lists = []

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

            elif (
                progress.next_review.date()
                <= today
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

            elif (
                progress.next_review.date()
                <= today
            ):

                is_due = True

            if is_due:

                due_definitions.append(
                    definition
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

    total_due_reviews = (
        due_formula_count
        +
        due_definition_count
        +
        due_bullet_list_count
    )

    # ========================================================
    # RENDER
    # ========================================================

    return render(
        request,
        "dashboard/subject_detail.html",
        {
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
            # TEXTBOOKS
            # --------------------------------------------

            "textbooks":
                textbooks,

            "total_textbook_pages":
                total_textbook_pages,

            "textbook_error":
                textbook_error,

            # --------------------------------------------
            # REVISION
            # --------------------------------------------

            "revision_days":
                revision_days,

            "revision_input_value":
                revision_input_value,

            "revision_error":
                revision_error,

            # --------------------------------------------
            # COUNTDOWN
            # --------------------------------------------

            "days_until_exam":
                days_until_exam,

            "study_days_left":
                study_days_left,

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

    # --------------------------------------------------------
    # VALIDATE SUBJECT INDEX
    # --------------------------------------------------------

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
        subject_index >= len(subjects)
    ):

        return redirect(
            "goals"
        )

    subject_data = subjects[
        subject_index
    ]

    # --------------------------------------------------------
    # FIND DATABASE SUBJECT
    # --------------------------------------------------------

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
            ).strip()
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

        term = request.POST.get(
            "term",
            ""
        ).strip()

        meaning = request.POST.get(
            "meaning",
            ""
        ).strip()

        if (
            term
            and meaning
            and database_subject
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
    # GET EXISTING DEFINITIONS
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

    # --------------------------------------------------------
    # RENDER
    # --------------------------------------------------------

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
# PROGRESS
# ============================================================

@login_required
def progress(request):

    # --------------------------------------------------------
    # GET ALL SUBJECTS FOR THIS STUDENT
    # --------------------------------------------------------

    subjects = (
        Subject.objects
        .filter(
            user=request.user
        )
        .order_by(
            "name"
        )
    )

    # --------------------------------------------------------
    # GET ALL KNOWLEDGE UNITS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # GET STUDENT PROGRESS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # OVERALL STATISTICS
    # --------------------------------------------------------

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
        + total_incorrect
    )

    # --------------------------------------------------------
    # ACCURACY
    # --------------------------------------------------------

    if total_reviews > 0:

        accuracy = round(
            (
                total_correct
                / total_reviews
            )
            * 100
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
                / total_knowledge
            )
            * 100
        )

    else:

        overall_mastery = 0

    # --------------------------------------------------------
    # SUBJECT PROGRESS
    # --------------------------------------------------------

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

        if subject_unit_count == 0:

            continue

        subject_progress_records = (
            progress_records
            .filter(
                knowledge_unit__in=(
                    subject_units
                )
            )
        )

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
            + subject_incorrect
        )

        if subject_total_answers > 0:

            subject_accuracy = round(
                (
                    subject_correct
                    / subject_total_answers
                )
                * 100
            )

        else:

            subject_accuracy = 0

        subject_mastery = round(
            (
                subject_mastered
                / subject_unit_count
            )
            * 100
        )

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
            }
        )

    # --------------------------------------------------------
    # RENDER
    # --------------------------------------------------------

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

            "subject_progress":
                subject_progress,
        }
    )
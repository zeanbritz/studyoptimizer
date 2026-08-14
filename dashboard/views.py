from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from learning.models import (
    Subject,
    Formula,
    Definition,
    KnowledgeUnit,
    StudentKnowledge,
)


@login_required
def dashboard(request):

    return render(
        request,
        "dashboard/dashboard.html"
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

            subject_count = int(subject_count)

        except (ValueError, TypeError):

            subject_count = 1

        subject_count = max(
            1,
            min(subject_count, 20)
        )

        request.session["onboarding_profile"] = {

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

        for i in range(subject_count):

            subjects.append({

                "name": "",

                "target_grade": "",

                "exam_date": "",

                "definitions": [],

                "formulas": [],

                "database_id": None,

            })

        request.session[
            "onboarding_subjects"
        ] = subjects

        request.session.modified = True

        return redirect("goals")

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

    return render(
        request,
        "dashboard/goals.html",
        {
            "profile": profile,
            "subjects": subjects,
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

    # ========================================================
    # VALIDATE SUBJECT INDEX
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
        or subject_index >= len(subjects)
    ):

        return redirect(
            "goals"
        )

    subject_data = subjects[
        subject_index
    ]

    # ========================================================
    # MAKE SURE OLD SESSION DATA HAS REQUIRED FIELDS
    # ========================================================

    if "definitions" not in subject_data:

        subject_data["definitions"] = []

    if "formulas" not in subject_data:

        subject_data["formulas"] = []

    if "database_id" not in subject_data:

        subject_data["database_id"] = None

    # ========================================================
    # SAVE SUBJECT INFORMATION
    # ========================================================

    if request.method == "POST":

        subject_data["name"] = request.POST.get(
            "name",
            ""
        ).strip()

        subject_data["target_grade"] = request.POST.get(
            "target_grade",
            ""
        )

        subject_data["exam_date"] = request.POST.get(
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

        # ----------------------------------------------------
        # Find database subject using the name.
        # ----------------------------------------------------

        database_subject = Subject.objects.filter(
            user=request.user,
            name=subject_data["name"]
        ).first()

        if database_subject:

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

        return redirect(
            "subject_detail",
            subject_index=subject_index
        )

    # ========================================================
    # FIND DATABASE SUBJECT
    # ========================================================

    database_subject = None

    database_subject_id = subject_data.get(
        "database_id"
    )

    # First try database ID.
    if database_subject_id:

        database_subject = Subject.objects.filter(
            id=database_subject_id,
            user=request.user
        ).first()

    # Fall back to subject name.
    if not database_subject:

        subject_name = subject_data.get(
            "name",
            ""
        ).strip()

        if subject_name:

            database_subject = Subject.objects.filter(
                user=request.user,
                name=subject_name
            ).first()

    # ========================================================
    # REVIEW ITEMS
    # ========================================================

    due_formulas = []

    due_definitions = []

    # ========================================================
    # FIND KNOWLEDGE UNITS FOR THIS SUBJECT
    # ========================================================

    if database_subject:

        today = timezone.localdate()

        knowledge_units = (
            KnowledgeUnit.objects.filter(
                subject=database_subject,
                active=True,
            )
        )

        # ====================================================
        # CHECK EACH KNOWLEDGE UNIT
        # ====================================================

        for knowledge_unit in knowledge_units:

            progress = (
                StudentKnowledge.objects.filter(
                    student=request.user,
                    knowledge_unit=knowledge_unit,
                ).first()
            )

            # ------------------------------------------------
            # A knowledge unit is due if:
            #
            # 1. It has never been reviewed
            # OR
            # 2. Its next_review is today or earlier
            # ------------------------------------------------

            is_due = False

            if progress is None:

                is_due = True

            elif progress.next_review is None:

                is_due = True

            elif progress.next_review.date() <= today:

                is_due = True

            if not is_due:

                continue

            # =================================================
            # FORMULA
            # =================================================

            if (
                knowledge_unit.knowledge_type
                == KnowledgeUnit.KnowledgeType.FORMULA
            ):

                formula = getattr(
                    knowledge_unit,
                    "formula",
                    None
                )

                if formula:

                    due_formulas.append(
                        formula
                    )

            # =================================================
            # DEFINITION
            # =================================================

            elif (
                knowledge_unit.knowledge_type
                == KnowledgeUnit.KnowledgeType.DEFINITION
            ):

                definition = getattr(
                    knowledge_unit,
                    "definition",
                    None
                )

                if definition:

                    due_definitions.append(
                        definition
                    )

    # ========================================================
    # RENDER PAGE
    # ========================================================

    return render(
        request,
        "dashboard/subject_detail.html",
        {

            "subject":
                subject_data,

            "subject_index":
                subject_index,

            "database_subject":
                database_subject,

            # ----------------------------------------------
            # FORMULA REVIEWS
            # ----------------------------------------------

            "due_formulas":
                due_formulas,

            "due_formula_count":
                len(due_formulas),

            # ----------------------------------------------
            # DEFINITION REVIEWS
            # ----------------------------------------------

            "due_definitions":
                due_definitions,

            "due_definition_count":
                len(due_definitions),

            # ----------------------------------------------
            # TOTAL
            # ----------------------------------------------

            "total_due_reviews":
                (
                    len(due_formulas)
                    +
                    len(due_definitions)
                ),

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
        return redirect("onboarding")

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    try:
        subject_index = int(
            subject_index
        )

    except (ValueError, TypeError):

        return redirect("goals")

    if (
        subject_index < 0
        or subject_index >= len(subjects)
    ):

        return redirect("goals")

    subject_data = subjects[
        subject_index
    ]

    # ========================================================
    # FIND DATABASE SUBJECT
    # ========================================================

    database_subject = None

    database_subject_id = (
        subject_data.get("database_id")
    )

    if database_subject_id:

        database_subject = Subject.objects.filter(
            id=database_subject_id,
            user=request.user
        ).first()

    if not database_subject:

        subject_name = subject_data.get(
            "name",
            ""
        ).strip()

        if subject_name:

            database_subject = Subject.objects.filter(
                user=request.user,
                name=subject_name
            ).first()

    # ========================================================
    # ADD DEFINITION
    # ========================================================

    if request.method == "POST":

        term = request.POST.get(
            "term",
            ""
        ).strip()

        meaning = request.POST.get(
            "meaning",
            ""
        ).strip()

        if term and meaning and database_subject:

            # ---------------------------------------------
            # Create KnowledgeUnit
            # ---------------------------------------------

            knowledge_unit = KnowledgeUnit.objects.create(
                subject=database_subject,
                title=term,
                knowledge_type=(
                    KnowledgeUnit.KnowledgeType.DEFINITION
                ),
                difficulty=1,
                estimated_minutes=2,
                active=True,
            )

            # ---------------------------------------------
            # Create Definition
            # ---------------------------------------------

            Definition.objects.create(
                knowledge_unit=knowledge_unit,
                term=term,
                definition=meaning,
            )

            # ---------------------------------------------
            # Create StudentKnowledge
            # ---------------------------------------------

            StudentKnowledge.objects.create(
                student=request.user,
                knowledge_unit=knowledge_unit,
            )

        return redirect(
            "definition",
            subject_index=subject_index
        )

    # ========================================================
    # RENDER
    # ========================================================

    definitions = []

    if database_subject:

        definitions = Definition.objects.filter(
            knowledge_unit__subject=database_subject
        ).select_related(
            "knowledge_unit"
        )

    return render(
        request,
        "dashboard/definition.html",
        {
            "subject": subject_data,
            "subject_index": subject_index,
            "definitions": definitions,
        }
    )
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from learning.models import (
    Subject,
    KnowledgeUnit,
    Formula,
    Definition,
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

    # ========================================================
    # GET ONBOARDING PROFILE
    # ========================================================

    profile = request.session.get(
        "onboarding_profile"
    )

    if not profile:
        return redirect("onboarding")


    # ========================================================
    # GET SUBJECTS FROM SESSION
    # ========================================================

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
    # MAKE SURE REQUIRED SESSION FIELDS EXIST
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


    # ========================================================
    # FIND DATABASE SUBJECT
    # ========================================================

    database_subject = None


    database_subject_id = subject_data.get(
        "database_id"
    )


    # ========================================================
    # FIRST: TRY DATABASE ID
    # ========================================================

    if database_subject_id:

        database_subject = (
            Subject.objects.filter(
                id=database_subject_id,
                user=request.user
            ).first()
        )


    # ========================================================
    # SECOND: TRY SUBJECT NAME
    # ========================================================

    if not database_subject:

        subject_name = subject_data.get(
            "name",
            ""
        ).strip()

        if subject_name:

            database_subject = (
                Subject.objects.filter(
                    user=request.user,
                    name=subject_name
                ).first()
            )


    # ========================================================
    # THIRD: CREATE DATABASE SUBJECT IF MISSING
    # ========================================================

    if not database_subject:

        subject_name = subject_data.get(
            "name",
            ""
        ).strip()

        if subject_name:

            database_subject = (
                Subject.objects.create(

                    user=request.user,

                    name=subject_name,

                )
            )


    # ========================================================
    # SAVE DATABASE ID
    # ========================================================

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


    # ========================================================
    # INITIALISE REVIEW LISTS
    # ========================================================

    due_formulas = []

    due_definitions = []


    # ========================================================
    # FIND EVERYTHING DUE FOR REVIEW
    # ========================================================

    if database_subject:

        today = timezone.localdate()


        # ====================================================
        # FORMULAS
        # ====================================================

        formula_knowledge_units = (
            KnowledgeUnit.objects.filter(

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


        for knowledge_unit in formula_knowledge_units:

            formula = getattr(
                knowledge_unit,
                "formula",
                None
            )

            if not formula:
                continue


            progress = (
                StudentKnowledge.objects.filter(

                    student=request.user,

                    knowledge_unit=knowledge_unit,

                ).first()
            )


            # Never reviewed = due

            if progress is None:

                due_formulas.append(
                    formula
                )

                continue


            # No next review = due

            if progress.next_review is None:

                due_formulas.append(
                    formula
                )

                continue


            # Review date reached

            if (
                progress.next_review.date()
                <= today
            ):

                due_formulas.append(
                    formula
                )


        # ====================================================
        # DEFINITIONS
        # ====================================================

        definition_knowledge_units = (
            KnowledgeUnit.objects.filter(

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


        for knowledge_unit in definition_knowledge_units:

            definition = getattr(
                knowledge_unit,
                "definition",
                None
            )

            if not definition:
                continue


            progress = (
                StudentKnowledge.objects.filter(

                    student=request.user,

                    knowledge_unit=knowledge_unit,

                ).first()
            )


            # Never reviewed = due

            if progress is None:

                due_definitions.append(
                    definition
                )

                continue


            # No next review = due

            if progress.next_review is None:

                due_definitions.append(
                    definition
                )

                continue


            # Review date reached

            if (
                progress.next_review.date()
                <= today
            ):

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

    total_due_reviews = (
        due_formula_count
        +
        due_definition_count
    )


    # ========================================================
    # RENDER
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

            # IMPORTANT:
            # Give the template the actual database ID.

            "subject_id":
                database_subject.id
                if database_subject
                else None,

            # -----------------------------------------------
            # FORMULAS
            # -----------------------------------------------

            "due_formulas":
                due_formulas,

            "due_formula_count":
                due_formula_count,

            # -----------------------------------------------
            # DEFINITIONS
            # -----------------------------------------------

            "due_definitions":
                due_definitions,

            "due_definition_count":
                due_definition_count,

            # -----------------------------------------------
            # TOTAL
            # -----------------------------------------------

            "total_due_reviews":
                total_due_reviews,

        }

    )

# ============================================================
# DEFINITIONS
# ============================================================

@login_required
def definition(request, subject_index):

    profile = request.session.get(
        "onboarding_profile"
    )

    if not profile:
        return redirect("onboarding")

    subjects = request.session.get(
        "onboarding_subjects",
        []
    )

    # ========================================================
    # VALIDATE SUBJECT INDEX
    # ========================================================

    try:
        subject_index = int(subject_index)

    except (ValueError, TypeError):
        return redirect("goals")

    if (
        subject_index < 0
        or subject_index >= len(subjects)
    ):
        return redirect("goals")

    subject_data = subjects[subject_index]

    # ========================================================
    # FIND DATABASE SUBJECT
    # ========================================================

    database_subject = None

    database_subject_id = subject_data.get(
        "database_id"
    )

    # First try database ID
    if database_subject_id:

        database_subject = Subject.objects.filter(
            id=database_subject_id,
            user=request.user
        ).first()

    # Fall back to subject name
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
    # SAVE DEFINITION
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

            # =================================================
            # CREATE KNOWLEDGE UNIT
            # =================================================

            knowledge_unit = KnowledgeUnit.objects.create(

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

            # =================================================
            # CREATE DEFINITION
            # =================================================

            Definition.objects.create(

                knowledge_unit=knowledge_unit,

                term=term,

                definition=meaning,

            )

        return redirect(
            "definition",
            subject_index=subject_index
        )

    # ========================================================
    # GET EXISTING DEFINITIONS
    # ========================================================

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
            .select_related("definition")
            .order_by("-created")
        )

        definitions = [
            knowledge_unit.definition
            for knowledge_unit in knowledge_units
            if hasattr(
                knowledge_unit,
                "definition"
            )
        ]

    # ========================================================
    # RENDER
    # ========================================================

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
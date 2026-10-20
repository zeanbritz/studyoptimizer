"""Shared Free, Grow and Bloom permissions for all study entry points."""

from functools import wraps
from inspect import signature

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect

from learning.models import KnowledgeUnit, Note, Subject

from .access import get_study_tier
from .models import StudyTier
from .plans import STUDY_PLANS


FREE_SUBJECT_LIMIT = STUDY_PLANS[StudyTier.FREE].subject_limit
FREE_LEARNING_ITEM_LIMIT = STUDY_PLANS[StudyTier.FREE].learning_items_per_subject


def is_free_student(user):
    return get_study_tier(user) == StudyTier.FREE


def get_subject_limit(user):
    plan = STUDY_PLANS.get(get_study_tier(user))
    return plan.subject_limit if plan else 0


def subject_count(user):
    return Subject.objects.filter(user=user).count()


def learning_item_count(user, *, subject=None):
    """Count all six study-item types, optionally scoped to an owned subject."""
    filters = {"subject__user": user}
    if subject is not None:
        filters["subject_id"] = subject.pk
    return KnowledgeUnit.objects.filter(**filters).count() + Note.objects.filter(**filters).count()


def can_create_subject(user, *, session_subject_count=0):
    if get_study_tier(user) is None:
        return False
    limit = get_subject_limit(user)
    return limit is None or max(subject_count(user), session_subject_count) < limit


def can_create_learning_item(user, *, subject=None):
    plan = STUDY_PLANS.get(get_study_tier(user))
    if plan is None or (subject is not None and subject.user_id != user.pk):
        return False
    if plan.learning_items_per_subject is None:
        return True
    return subject is not None and learning_item_count(user, subject=subject) < plan.learning_items_per_subject


def can_export_subject_summary(user):
    return get_study_tier(user) in {StudyTier.GROW, StudyTier.BLOOM}


def can_use_pdf_summarizer(user):
    # Existing suggestions remain editable after the month's page allowance is used.
    return get_study_tier(user) in {StudyTier.GROW, StudyTier.BLOOM}


def _item_subject(request, value, *, workspace_index):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    if not workspace_index:
        return Subject.objects.filter(user=request.user, pk=value).first()
    subjects = request.session.get("onboarding_subjects", [])
    if value < 0 or value >= len(subjects) or not isinstance(subjects[value], dict):
        return None
    entry = subjects[value]
    try:
        database_id = int(entry.get("database_id"))
    except (TypeError, ValueError):
        database_id = None
    subject = Subject.objects.filter(user=request.user, pk=database_id).first()
    if subject is None and entry.get("name"):
        subject = Subject.objects.filter(user=request.user, name=entry["name"]).order_by("created", "id").first()
    return subject


def free_learning_item_limit(view):
    """Enforce the selected subject's limit, including the older workspace route."""
    workspace_index = "subject_index" in signature(view).parameters
    parameter = "subject_index" if workspace_index else "subject_id"

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        subject = _item_subject(
            request, kwargs.get(parameter, args[0] if args else None),
            workspace_index=workspace_index,
        )
        if subject is None:
            # Let the view perform its normal invalid-subject handling.
            return view(request, *args, **kwargs)
        if request.method == "POST":
            with transaction.atomic():
                account = get_user_model().objects.select_for_update().get(pk=request.user.pk)
                if not can_create_learning_item(account, subject=subject):
                    return redirect("pricing")
                return view(request, *args, **kwargs)
        if not can_create_learning_item(request.user, subject=subject):
            return redirect("pricing")
        return view(request, *args, **kwargs)

    return wrapped

"""Feature limits for the current Free plan.

Future paid tiers can extend this policy without scattering billing checks through
the study views. The PDF scanner remains an owner-only experiment for now.
"""

from functools import wraps

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect

from learning.models import KnowledgeUnit, Note, Subject

from .access import (
    ACCESS_FREE, ACCESS_FULL, get_study_access_level,
    has_permanent_free_access,
)


FREE_SUBJECT_LIMIT = 2
FREE_LEARNING_ITEM_LIMIT = 100


def is_free_student(user):
    return get_study_access_level(user) == ACCESS_FREE


def subject_count(user):
    return Subject.objects.filter(user=user).count()


def learning_item_count(user):
    """Count the five knowledge-unit types plus notes across all subjects."""
    return (
        KnowledgeUnit.objects.filter(subject__user=user).count()
        + Note.objects.filter(subject__user=user).count()
    )


def can_create_subject(user, *, session_subject_count=0):
    access = get_study_access_level(user)
    if access == ACCESS_FULL:
        return True
    if access != ACCESS_FREE:
        return False
    return max(subject_count(user), session_subject_count) < FREE_SUBJECT_LIMIT


def can_create_learning_item(user):
    access = get_study_access_level(user)
    if access == ACCESS_FULL:
        return True
    return access == ACCESS_FREE and learning_item_count(user) < FREE_LEARNING_ITEM_LIMIT


def can_export_subject_summary(user):
    """Reserve PDF exports until the top paid tier is defined.

    Existing beta invitees retain their promised permanent access.
    """
    return has_permanent_free_access(user)


def can_use_pdf_summarizer(user):
    """Keep the scanner private until its paid-tier placement is decided."""
    return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


def free_learning_item_limit(view):
    """Redirect a full Free account before any create view can write an item."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method == "POST":
            # Serialize simultaneous creates for the same user on PostgreSQL.
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=request.user.pk)
                if not can_create_learning_item(request.user):
                    return redirect("pricing")
                return view(request, *args, **kwargs)
        if not can_create_learning_item(request.user):
            return redirect("pricing")
        return view(request, *args, **kwargs)

    return wrapped

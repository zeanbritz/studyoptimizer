from django.utils import timezone

from .models import BetaInvite, StudyMembership


ACCESS_NONE = "none"
ACCESS_READ_ONLY = "read_only"
ACCESS_FULL = "full"


def has_permanent_free_access(user):
    """Return whether an active user can study without a subscription."""
    if not user or not user.is_authenticated or not user.is_active:
        return False

    if user.is_superuser or user.beta_lifetime_access:
        return True

    # Protect claimed invitees if an older signup missed the flag.
    return BetaInvite.objects.filter(claimed_by_id=user.pk).exists()


def get_study_access_level(user):
    """Return full, read-only, or no study access."""
    if not user or not user.is_authenticated or not user.is_active:
        return ACCESS_NONE

    if has_permanent_free_access(user):
        return ACCESS_FULL

    membership = StudyMembership.objects.filter(user_id=user.pk).first()
    if membership is None or membership.paid_until is None:
        return ACCESS_NONE

    now = timezone.now()
    full_access_statuses = {
        StudyMembership.Status.ACTIVE,
        StudyMembership.Status.NON_RENEWING,
        StudyMembership.Status.PAST_DUE,
    }

    if membership.status in full_access_statuses:
        if membership.paid_until > now:
            return ACCESS_FULL

        if (
            membership.status == StudyMembership.Status.PAST_DUE
            and membership.grace_until is not None
            and membership.grace_until > now
        ):
            return ACCESS_FULL

    if membership.paid_until <= now:
        return ACCESS_READ_ONLY

    return ACCESS_NONE


def has_study_access(user):
    """Return whether the user may use paid study features."""
    return get_study_access_level(user) == ACCESS_FULL


def can_view_existing_study_data(user):
    """Return whether the user may view existing study material."""
    return get_study_access_level(user) in {
        ACCESS_FULL,
        ACCESS_READ_ONLY,
    }
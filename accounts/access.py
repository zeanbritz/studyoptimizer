from django.conf import settings
from django.utils import timezone

from .models import BetaInvite, StudyMembership, StudyTier


ACCESS_NONE = "none"
ACCESS_FREE = "free"
ACCESS_READ_ONLY = "read_only"
ACCESS_FULL = "full"


def has_permanent_free_access(user):
    """Return whether an active user can study without a subscription."""
    if not user or not user.is_authenticated or not user.is_active or user.pk is None:
        return False

    if user.is_superuser or user.beta_lifetime_access:
        return True

    # Protect claimed invitees if an older signup missed the flag.
    return BetaInvite.objects.filter(claimed_by_id=user.pk).exists()


def get_study_tier(user):
    """Return the effective tier; feature limits live in accounts.entitlements."""
    if not user or not user.is_authenticated or not user.is_active or user.pk is None:
        return None

    if has_permanent_free_access(user):
        return StudyTier.BLOOM

    membership = StudyMembership.objects.filter(user_id=user.pk).first()
    if membership is None or membership.paid_until is None:
        return StudyTier.FREE

    # Sandbox purchases must never unlock paid tools on a production deployment.
    if membership.payment_mode == StudyMembership.PaymentMode.TEST and not (
        settings.DEBUG and getattr(settings, "PAYSTACK_TEST_CHECKOUT_ENABLED", False)
    ):
        return StudyTier.FREE

    if membership.tier not in {StudyTier.GROW, StudyTier.BLOOM}:
        return StudyTier.FREE

    now = timezone.now()
    full_access_statuses = {
        StudyMembership.Status.ACTIVE,
        StudyMembership.Status.NON_RENEWING,
        StudyMembership.Status.PAST_DUE,
    }

    if membership.status in full_access_statuses:
        if membership.paid_until > now:
            return StudyTier(membership.tier)

        if (
            membership.status == StudyMembership.Status.PAST_DUE
            and membership.grace_until is not None
            and membership.grace_until > now
        ):
            return StudyTier(membership.tier)

    return StudyTier.FREE


def get_study_access_level(user):
    """Keep the existing entitlement policy while distinguishing paid tiers."""
    tier = get_study_tier(user)
    if tier is None:
        return ACCESS_NONE
    if tier == StudyTier.FREE:
        return ACCESS_FREE
    return ACCESS_FULL


def has_study_access(user):
    """Return whether the user may use paid study features."""
    return get_study_access_level(user) == ACCESS_FULL


def can_view_existing_study_data(user):
    """Return whether the user may view existing study material."""
    return get_study_access_level(user) in {
        ACCESS_FULL,
        ACCESS_FREE,
        ACCESS_READ_ONLY,
    }

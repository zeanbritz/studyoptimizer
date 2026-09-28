from .models import BetaInvite


def has_permanent_free_access(user):
    """Return whether an active user can study without a subscription."""
    if not user or not user.is_authenticated or not user.is_active:
        return False

    if user.is_superuser or user.beta_lifetime_access:
        return True

    # Also protect claimed invitees if an older signup missed the flag.
    return BetaInvite.objects.filter(claimed_by_id=user.pk).exists()

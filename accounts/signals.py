"""Account events that are useful to support staff in the Django admin."""

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db import DatabaseError
from django.db.models import F
from django.dispatch import receiver

from .models import UserActivity


def _request_path(request):
    """Return a short, query-string-free path for an event."""
    if request is None:
        return ""
    return str(getattr(request, "path_info", ""))[:255]


@receiver(user_logged_in, dispatch_uid="accounts.track_successful_login")
def track_successful_login(sender, request, user, **kwargs):
    """Keep an accurate successful-login count and a matching timeline item."""
    if not getattr(user, "pk", None):
        return

    try:
        get_user_model().objects.filter(pk=user.pk).update(
            login_count=F("login_count") + 1,
        )
        UserActivity.objects.create(
            user_id=user.pk,
            activity_type=UserActivity.ActivityType.LOGIN,
            label="Signed in",
            path=_request_path(request),
        )
    except DatabaseError:
        # Activity history must never prevent a student from signing in while a
        # deployment is applying its schema update.
        return


@receiver(user_logged_out, dispatch_uid="accounts.track_successful_logout")
def track_successful_logout(sender, request, user, **kwargs):
    """Add a logout marker when Django has an authenticated user to identify."""
    if not getattr(user, "pk", None):
        return

    try:
        UserActivity.objects.create(
            user_id=user.pk,
            activity_type=UserActivity.ActivityType.LOGOUT,
            label="Signed out",
            path=_request_path(request),
        )
    except DatabaseError:
        return

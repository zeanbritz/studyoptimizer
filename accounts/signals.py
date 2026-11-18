"""Account events used for account administration and operator alerts."""

import logging

from allauth.account.signals import user_signed_up
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.core.mail import EmailMessage
from django.db import DatabaseError
from django.db.models import F
from django.dispatch import receiver
from django.utils import timezone

from .models import UserActivity


logger = logging.getLogger(__name__)


def _request_path(request):
    """Return a short, query-string-free path for an event."""
    if request is None:
        return ""
    return str(getattr(request, "path_info", ""))[:255]


@receiver(user_signed_up, dispatch_uid="accounts.notify_operator_of_signup")
def notify_operator_of_signup(sender, request, user, **kwargs):
    """Email the configured operator when an account has been created."""
    recipient = getattr(
        settings,
        "STUDIGARDEN_SIGNUP_NOTIFICATION_EMAIL",
        "",
    ).strip()
    if not recipient or not getattr(user, "email", ""):
        return

    joined_at = timezone.localtime(user.date_joined).strftime(
        "%d %B %Y, %H:%M %Z"
    )
    message = EmailMessage(
        subject="New StudiGarden sign-up",
        body=(
            "A new StudiGarden account was created.\n\n"
            f"Username: {user.get_username()}\n"
            f"Email: {user.email}\n"
            f"Signed up: {joined_at}\n\n"
            "The student must still confirm their email address before using "
            "their account."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        reply_to=[user.email],
    )
    try:
        message.send(fail_silently=False)
    except Exception:
        # The operator alert must never prevent a legitimate account signup.
        logger.exception("Could not send StudiGarden signup notification")


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

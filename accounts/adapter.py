import uuid

from allauth.account.adapter import DefaultAccountAdapter
from django.db import transaction
from django.utils import timezone

from .models import BetaInvite


class InviteUnavailable(Exception):
    pass


def invite_token_from_request(request):
    if request.method == "POST":
        raw_token = request.POST.get("invite_token")
    else:
        raw_token = request.GET.get("invite")

    try:
        return uuid.UUID(raw_token)
    except (TypeError, ValueError, AttributeError):
        return None


class BetaInviteAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        token = invite_token_from_request(request)

        if token is None:
            return False

        return BetaInvite.objects.filter(
            token=token,
            is_active=True,
            claimed_by__isnull=True,
        ).exists()

    @transaction.atomic
    def save_user(self, request, user, form, commit=True):
        if not commit:
            raise ValueError("Invite-only signup requires commit=True.")

        token = invite_token_from_request(request)

        if token is None:
            raise InviteUnavailable()

        invite = (
            BetaInvite.objects.select_for_update()
            .filter(
                token=token,
                is_active=True,
                claimed_by__isnull=True,
            )
            .first()
        )

        if invite is None:
            raise InviteUnavailable()

        saved_user = super().save_user(
            request,
            user,
            form,
            commit=True,
        )

        invite.claimed_by = saved_user
        invite.claimed_at = timezone.now()
        invite.save(update_fields=["claimed_by", "claimed_at"])

        return saved_user
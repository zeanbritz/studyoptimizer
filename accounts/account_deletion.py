import uuid

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from dashboard.models import BetaFeedback, DailyReviewPlan, StudyAvailability, StudyProfile
from learning.models import StudentKnowledge, Subject

from .models import (
    StudyMembership,
    StudyMonthlyUsage,
    StudyPayment,
    StudyPlanChange,
    StudyRefund,
    SupportQuery,
)
from .plan_changes import OPEN_CHANGE_STATES


OPEN_REFUND_STATES = (
    StudyRefund.Status.REQUESTED,
    StudyRefund.Status.APPROVED,
    StudyRefund.Status.SUBMITTING,
    StudyRefund.Status.PROCESSING,
    StudyRefund.Status.ATTENTION,
)


def account_deletion_blocker(user):
    """Return a safe, user-facing reason why deletion must wait."""
    if not user or not user.is_authenticated or not user.pk or not user.is_active:
        return "An active account is required."
    if user.is_staff or user.is_superuser:
        return "Administrator accounts cannot be deleted from Profile."
    if StudyPlanChange.objects.filter(user_id=user.pk, state__in=OPEN_CHANGE_STATES).exists():
        return "Finish or cancel the plan change currently in progress before deleting your account."
    if StudyRefund.objects.filter(user_id=user.pk, status__in=OPEN_REFUND_STATES).exists():
        return "Wait for the refund currently in progress before deleting your account."

    membership = StudyMembership.objects.filter(user_id=user.pk).first()
    renewable_membership = bool(
        membership
        and membership.plan == StudyMembership.Plan.MONTHLY
        and (
            membership.status in {
                StudyMembership.Status.ACTIVE,
                StudyMembership.Status.PAST_DUE,
            }
            or (
                membership.paystack_subscription_code
                and membership.status != StudyMembership.Status.NON_RENEWING
            )
        )
    )
    if renewable_membership:
        return "Cancel your monthly subscription and wait for Profile to confirm that future renewals are stopped before deleting your account."
    return ""


def account_deletion_context(user):
    blocker = account_deletion_blocker(user)
    return {
        "can_delete_account": not blocker,
        "account_deletion_blocker": blocker,
    }


@transaction.atomic
def erase_student_account(user):
    """Erase study data and anonymise the login while retaining billing audits."""
    locked = get_user_model().objects.select_for_update().get(pk=user.pk)
    blocker = account_deletion_blocker(locked)
    if blocker:
        raise ValueError(blocker)

    now = timezone.now()

    # Any unpaid checkout is retired before the account loses access. A late
    # provider payment remains detectable by the existing recovery workflow.
    StudyPayment.objects.filter(
        user_id=locked.pk,
        source=StudyPayment.Source.CHECKOUT,
        discarded_at__isnull=True,
        status__in=(
            StudyPayment.Status.CREATED,
            StudyPayment.Status.PENDING,
            StudyPayment.Status.FAILED,
            StudyPayment.Status.ABANDONED,
        ),
    ).update(discarded_at=now, authorization_url="")

    # These records contain the student's actual study workspace and progress.
    Subject.objects.filter(user_id=locked.pk).delete()
    StudentKnowledge.objects.filter(student_id=locked.pk).delete()
    StudyProfile.objects.filter(user_id=locked.pk).delete()
    StudyAvailability.objects.filter(user_id=locked.pk).delete()
    DailyReviewPlan.objects.filter(user_id=locked.pk).delete()
    BetaFeedback.objects.filter(user_id=locked.pk).delete()
    StudyMonthlyUsage.objects.filter(user_id=locked.pk).delete()

    # Support and financial audit records remain available but no longer point
    # to an active student profile. Their snapshots are retained as disclosed.
    SupportQuery.objects.filter(user_id=locked.pk).update(user=None)
    EmailAddress.objects.filter(user_id=locked.pk).delete()

    locked.groups.clear()
    locked.user_permissions.clear()
    locked.username = f"deleted-{locked.pk}-{uuid.uuid4().hex[:12]}"
    locked.email = ""
    locked.first_name = ""
    locked.last_name = ""
    locked.beta_lifetime_access = False
    locked.is_active = False
    locked.deleted_at = now
    locked.set_unusable_password()
    locked.save(
        update_fields=(
            "username",
            "email",
            "first_name",
            "last_name",
            "beta_lifetime_access",
            "is_active",
            "deleted_at",
            "password",
        )
    )
    return locked

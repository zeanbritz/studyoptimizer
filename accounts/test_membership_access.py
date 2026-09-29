from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.utils import timezone

from .access import (
    ACCESS_FULL,
    ACCESS_NONE,
    ACCESS_READ_ONLY,
    can_view_existing_study_data,
    get_study_access_level,
    has_study_access,
)
from .models import BetaInvite, StudyMembership


class StudyMembershipAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="membership-student",
            password="safe-test-password",
        )

    def test_anonymous_and_inactive_users_have_no_access(self):
        self.assertEqual(get_study_access_level(AnonymousUser()), ACCESS_NONE)

        self.user.is_active = False
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["is_active", "beta_lifetime_access"])

        self.assertEqual(get_study_access_level(self.user), ACCESS_NONE)

    def test_user_without_membership_has_no_access(self):
        self.assertEqual(get_study_access_level(self.user), ACCESS_NONE)
        self.assertFalse(has_study_access(self.user))
        self.assertFalse(can_view_existing_study_data(self.user))

    def test_pending_payment_never_grants_access(self):
        membership = StudyMembership.objects.create(
            user=self.user,
            plan=StudyMembership.Plan.MONTHLY,
        )
        self.assertEqual(get_study_access_level(self.user), ACCESS_NONE)

        membership.paid_until = timezone.now() + timedelta(days=30)
        membership.save(update_fields=["paid_until"])
        self.assertEqual(get_study_access_level(self.user), ACCESS_NONE)

    def test_active_monthly_membership_has_full_access(self):
        StudyMembership.objects.create(
            user=self.user,
            plan=StudyMembership.Plan.MONTHLY,
            status=StudyMembership.Status.ACTIVE,
            paid_until=timezone.now() + timedelta(days=30),
        )

        self.assertEqual(get_study_access_level(self.user), ACCESS_FULL)
        self.assertTrue(has_study_access(self.user))

    def test_non_renewing_membership_keeps_paid_access(self):
        StudyMembership.objects.create(
            user=self.user,
            plan=StudyMembership.Plan.MONTHLY,
            status=StudyMembership.Status.NON_RENEWING,
            paid_until=timezone.now() + timedelta(days=5),
        )

        self.assertEqual(get_study_access_level(self.user), ACCESS_FULL)

    def test_expired_yearly_access_becomes_read_only(self):
        membership = StudyMembership.objects.create(
            user=self.user,
            plan=StudyMembership.Plan.YEARLY,
            status=StudyMembership.Status.ACTIVE,
            paid_until=timezone.now() + timedelta(days=30),
        )
        self.assertEqual(get_study_access_level(self.user), ACCESS_FULL)

        membership.paid_until = timezone.now() - timedelta(days=1)
        membership.status = StudyMembership.Status.EXPIRED
        membership.save(update_fields=["paid_until", "status"])

        self.assertEqual(get_study_access_level(self.user), ACCESS_READ_ONLY)
        self.assertFalse(has_study_access(self.user))
        self.assertTrue(can_view_existing_study_data(self.user))

    def test_failed_renewal_uses_grace_period(self):
        membership = StudyMembership.objects.create(
            user=self.user,
            plan=StudyMembership.Plan.MONTHLY,
            status=StudyMembership.Status.PAST_DUE,
            paid_until=timezone.now() - timedelta(days=1),
            grace_until=timezone.now() + timedelta(days=6),
        )
        self.assertEqual(get_study_access_level(self.user), ACCESS_FULL)

        membership.grace_until = timezone.now() - timedelta(hours=1)
        membership.save(update_fields=["grace_until"])
        self.assertEqual(get_study_access_level(self.user), ACCESS_READ_ONLY)

    def test_beta_flag_grants_permanent_full_access(self):
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])

        self.assertEqual(get_study_access_level(self.user), ACCESS_FULL)

    def test_claimed_beta_invite_grants_full_access_without_flag(self):
        invite = BetaInvite.objects.get(slot=1)
        invite.claimed_by = self.user
        invite.save(update_fields=["claimed_by"])

        self.assertEqual(get_study_access_level(self.user), ACCESS_FULL)

    def test_superuser_has_full_access(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])

        self.assertEqual(get_study_access_level(self.user), ACCESS_FULL)
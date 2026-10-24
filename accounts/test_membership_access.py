from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from learning.models import KnowledgeUnit, Note, Subject

from .access import (
    ACCESS_FULL,
    ACCESS_FREE,
    ACCESS_NONE,
    can_view_existing_study_data,
    get_study_access_level,
    has_study_access,
)
from .models import BetaInvite, StudyMembership
from .entitlements import (
    can_create_learning_item,
    can_create_subject,
    can_export_subject_summary,
    can_use_pdf_summarizer,
    learning_item_count,
)


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

    def test_user_without_membership_has_free_access(self):
        self.assertEqual(get_study_access_level(self.user), ACCESS_FREE)
        self.assertFalse(has_study_access(self.user))
        self.assertTrue(can_view_existing_study_data(self.user))

    def test_pending_payment_never_grants_paid_access(self):
        membership = StudyMembership.objects.create(
            user=self.user,
            plan=StudyMembership.Plan.MONTHLY,
        )
        self.assertEqual(get_study_access_level(self.user), ACCESS_FREE)

        membership.paid_until = timezone.now() + timedelta(days=30)
        membership.save(update_fields=["paid_until"])
        self.assertEqual(get_study_access_level(self.user), ACCESS_FREE)

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

    def test_expired_yearly_access_becomes_free(self):
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

        self.assertEqual(get_study_access_level(self.user), ACCESS_FREE)
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
        self.assertEqual(get_study_access_level(self.user), ACCESS_FREE)

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
        self.assertTrue(can_use_pdf_summarizer(self.user))


class FreePlanEntitlementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="free-student", password="Safe-test-password-123!"
        )
        self.client.force_login(self.user)
        self.subject = Subject.objects.create(user=self.user, name="Physics")

    def add_units(self, number):
        KnowledgeUnit.objects.bulk_create([
            KnowledgeUnit(
                subject=self.subject,
                title=f"Definition {index}",
                knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
            )
            for index in range(number)
        ])

    def test_free_limit_counts_notes_and_knowledge_items(self):
        self.add_units(98)
        Note.objects.create(subject=self.subject, title="Extra", content="Study note")
        self.assertEqual(learning_item_count(self.user), 99)
        self.assertTrue(can_create_learning_item(self.user, subject=self.subject))
        Note.objects.create(subject=self.subject, title="Last", content="Study note")
        self.assertEqual(learning_item_count(self.user), 100)
        self.assertFalse(can_create_learning_item(self.user, subject=self.subject))

    def test_second_subject_allowed_and_third_blocked(self):
        self.assertTrue(can_create_subject(self.user, session_subject_count=1))
        Subject.objects.create(user=self.user, name="Chemistry")
        self.assertFalse(can_create_subject(self.user))
        self.assertRedirects(
            self.client.post(reverse("onboarding"), {
                "workspace_name": "Science", "subject_count": "3", "study_hours": "10",
            }), reverse("pricing"),
        )

    def test_add_subject_action_redirects_when_two_exist(self):
        Subject.objects.create(user=self.user, name="Chemistry")
        session = self.client.session
        session["onboarding_profile"] = {"workspace_name": "Science", "subject_count": 2}
        session["onboarding_subjects"] = [
            {"name": "Physics", "database_id": self.subject.pk},
            {"name": "Chemistry", "database_id": None},
        ]
        session.save()
        self.assertRedirects(
            self.client.post(reverse("goals"), {"action": "add_subject"}),
            reverse("pricing"),
        )
        self.assertEqual(len(self.client.session["onboarding_subjects"]), 2)

    def test_session_cannot_create_third_database_subject(self):
        Subject.objects.create(user=self.user, name="Chemistry")
        session = self.client.session
        session["onboarding_profile"] = {"workspace_name": "Science", "subject_count": 3}
        session["onboarding_subjects"] = [
            {"name": "Physics", "database_id": self.subject.pk},
            {"name": "Chemistry", "database_id": None},
            {"name": "Biology", "database_id": None},
        ]
        session.save()
        self.assertEqual(self.client.get(reverse("subject_detail", args=[2])).status_code, 403)
        self.assertEqual(len(self.client.session["onboarding_subjects"]), 2)
        self.assertFalse(Subject.objects.filter(user=self.user, name="Biology").exists())

    def test_all_manual_create_routes_redirect_when_100_items_exist(self):
        self.add_units(100)
        for name in (
            "create_formula", "create_definition", "create_list",
            "create_steps", "create_note", "create_comparison",
        ):
            with self.subTest(name=name):
                url = reverse(name, args=[self.subject.pk])
                self.assertRedirects(self.client.get(url), reverse("pricing"))
                self.assertRedirects(self.client.post(url), reverse("pricing"))
        self.assertRedirects(
            self.client.post(reverse("definition", args=[0]), {
                "term": "Bypass", "meaning": "Not saved",
            }), reverse("pricing"),
        )
        self.assertEqual(learning_item_count(self.user), 100)

    def test_free_pdf_actions_redirect_to_pricing(self):
        self.assertFalse(can_export_subject_summary(self.user))
        self.assertFalse(can_use_pdf_summarizer(self.user))
        for name in ("download_subject_summary", "definition_pdf_lab"):
            self.assertRedirects(
                self.client.get(reverse(name, args=[self.subject.pk])),
                reverse("pricing"),
            )

    def test_beta_and_paid_accounts_are_not_subject_or_item_limited(self):
        self.add_units(100)
        Subject.objects.create(user=self.user, name="Chemistry")
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        self.assertTrue(can_create_subject(self.user))
        self.assertTrue(can_create_learning_item(self.user))
        self.assertTrue(can_export_subject_summary(self.user))
        self.assertTrue(can_use_pdf_summarizer(self.user))

        self.user.beta_lifetime_access = False
        self.user.save(update_fields=["beta_lifetime_access"])
        StudyMembership.objects.create(
            user=self.user, plan=StudyMembership.Plan.MONTHLY,
            status=StudyMembership.Status.ACTIVE,
            paid_until=timezone.now() + timedelta(days=30),
        )
        self.assertTrue(can_create_subject(self.user))
        self.assertTrue(can_create_learning_item(self.user))
        self.assertTrue(can_export_subject_summary(self.user))

    def test_expired_member_keeps_data_under_free_limits(self):
        self.add_units(100)
        StudyMembership.objects.create(
            user=self.user, plan=StudyMembership.Plan.YEARLY,
            status=StudyMembership.Status.EXPIRED,
            paid_until=timezone.now() - timedelta(days=1),
        )
        self.assertFalse(can_create_learning_item(self.user, subject=self.subject))
        self.assertEqual(learning_item_count(self.user), 100)

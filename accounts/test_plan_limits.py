from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from learning.models import KnowledgeUnit, Note, Subject

from .entitlements import can_create_learning_item, can_create_subject
from .middleware import WorkspaceSessionPersistenceMiddleware
from .models import StudyMembership, StudyMonthlyUsage, StudyTier
from .pdf_usage import PDFLimitExceeded, get_pdf_usage, monthly_pdf_allowance


class PlanLimitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="limits-student")
        cls.subject = Subject.objects.create(user=cls.user, name="Physics")

    def paid(self, tier=StudyTier.GROW):
        StudyMembership.objects.update_or_create(user=self.user, defaults={
            "tier": tier, "plan": StudyMembership.Plan.MONTHLY,
            "status": StudyMembership.Status.ACTIVE,
            "paid_until": timezone.now() + timedelta(days=365),
        })

    def test_free_cap_is_per_subject_and_combines_notes_with_other_learning_items(self):
        second = Subject.objects.create(user=self.user, name="Chemistry")
        KnowledgeUnit.objects.bulk_create([
            KnowledgeUnit(subject=self.subject, title=f"Term {i}", knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION)
            for i in range(99)
        ])
        Note.objects.create(subject=self.subject, title="Last item", content="Note")
        self.assertFalse(can_create_learning_item(self.user, subject=self.subject))
        self.assertTrue(can_create_learning_item(self.user, subject=second))
        self.client.force_login(self.user)
        for route in ("create_formula", "create_definition", "create_list", "create_steps", "create_note", "create_comparison"):
            with self.subTest(route=route):
                self.assertRedirects(self.client.get(reverse(route, args=[self.subject.pk])), reverse("pricing"))
                self.assertEqual(self.client.get(reverse(route, args=[second.pk])).status_code, 200)
        self.assertEqual(KnowledgeUnit.objects.filter(subject=self.subject).count(), 99)

    def test_free_legacy_workspace_create_is_limited_by_the_selected_subject(self):
        second = Subject.objects.create(user=self.user, name="Chemistry")
        KnowledgeUnit.objects.bulk_create([
            KnowledgeUnit(subject=self.subject, title=f"Term {i}", knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION)
            for i in range(100)
        ])
        self.client.force_login(self.user)
        response = self.client.post(reverse("definition", args=[1]), {"term": "Mole", "meaning": "Amount of substance"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(KnowledgeUnit.objects.filter(subject=second).count(), 1)
        self.assertRedirects(
            self.client.post(reverse("definition", args=[0]), {"term": "Blocked", "meaning": "Full subject"}),
            reverse("pricing"),
        )

    def test_grow_allows_seven_subjects_and_unlimited_learning_items(self):
        self.paid()
        Subject.objects.bulk_create([Subject(user=self.user, name=f"Extra {i}") for i in range(6)])
        self.assertFalse(can_create_subject(self.user))
        self.assertTrue(can_create_learning_item(self.user, subject=self.subject))
        self.client.force_login(self.user)
        self.assertRedirects(self.client.post(reverse("goals"), {"action": "add_subject"}), reverse("pricing"))
        self.assertRedirects(
            self.client.post(reverse("onboarding"), {"workspace_name": "Study", "subject_count": "8"}),
            reverse("pricing"),
        )
        self.assertEqual(Subject.objects.filter(user=self.user).count(), 7)

    def test_workspace_persistence_cannot_create_eighth_subject(self):
        self.paid()
        request = RequestFactory().get("/")
        request.user = self.user
        request.session = self.client.session
        request.session["onboarding_subjects"] = [
            {"name": f"Saved subject {i}"} for i in range(8)
        ]
        WorkspaceSessionPersistenceMiddleware._save_workspace(request)
        self.assertEqual(Subject.objects.filter(user=self.user).count(), 7)

    def test_bloom_can_add_subjects_beyond_the_previous_twenty_subject_cap(self):
        self.paid(StudyTier.BLOOM)
        Subject.objects.bulk_create([Subject(user=self.user, name=f"Extra {i}") for i in range(20)])
        self.client.force_login(self.user)
        self.client.post(reverse("goals"), {"action": "add_subject"})
        self.assertEqual(len(self.client.session["onboarding_subjects"]), 22)

    def test_monthly_allowance_resets_and_is_shared_across_requests(self):
        self.paid()
        with patch("accounts.pdf_usage.current_usage_month", return_value=date(2026, 10, 1)):
            for _ in range(2):
                with monthly_pdf_allowance(self.user) as allowance:
                    allowance.add_export()
            with self.assertRaises(PDFLimitExceeded):
                with monthly_pdf_allowance(self.user) as allowance:
                    allowance.add_export()
            with monthly_pdf_allowance(self.user) as allowance:
                allowance.add_summary_pages(5)
            with self.assertRaises(PDFLimitExceeded):
                with monthly_pdf_allowance(self.user) as allowance:
                    allowance.add_summary_pages(1)
            usage = get_pdf_usage(self.user)
            self.assertEqual((usage["pdf_exports"], usage["summary_pages"]), (2, 5))
        with patch("accounts.pdf_usage.current_usage_month", return_value=date(2026, 11, 1)):
            self.assertEqual(get_pdf_usage(self.user)["pages_remaining"], 5)
            with monthly_pdf_allowance(self.user) as allowance:
                allowance.add_export()
        self.assertEqual(StudyMonthlyUsage.objects.filter(user=self.user).count(), 2)

    def test_failed_work_rolls_back_the_allowance(self):
        self.paid()
        with self.assertRaises(RuntimeError):
            with monthly_pdf_allowance(self.user) as allowance:
                allowance.add_export()
                allowance.add_summary_pages(3)
                raise RuntimeError("Processing failed")
        self.assertFalse(StudyMonthlyUsage.objects.filter(user=self.user).exists())

    def test_bloom_and_beta_members_have_no_monthly_pdf_quota(self):
        for beta in (False, True):
            with self.subTest(beta=beta):
                if not beta:
                    self.paid(StudyTier.BLOOM)
                else:
                    StudyMembership.objects.filter(user=self.user).delete()
                    self.user.beta_lifetime_access = True
                    self.user.save(update_fields=["beta_lifetime_access"])
                with monthly_pdf_allowance(self.user) as allowance:
                    for _ in range(3):
                        allowance.add_export()
                    allowance.add_summary_pages(60)
                self.assertIsNone(get_pdf_usage(self.user)["pages_remaining"])

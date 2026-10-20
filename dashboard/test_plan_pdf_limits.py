from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from reportlab.pdfgen import canvas

from accounts.models import StudyMembership, StudyMonthlyUsage, StudyTier
from accounts.pdf_usage import get_pdf_usage
from learning.models import Definition, Subject


class PlanPdfLimitsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="grow-pdf-student")
        cls.subject = Subject.objects.create(user=cls.user, name="Biology")
        cls.second = Subject.objects.create(user=cls.user, name="Chemistry")
        StudyMembership.objects.create(
            user=cls.user, tier=StudyTier.GROW, plan=StudyMembership.Plan.MONTHLY,
            status=StudyMembership.Status.ACTIVE,
            paid_until=timezone.now() + timedelta(days=365),
        )

    def setUp(self):
        self.client.force_login(self.user)

    @staticmethod
    def pdf_upload(pages):
        buffer = BytesIO()
        document = canvas.Canvas(buffer, pageCompression=0)
        for _ in range(pages):
            document.drawString(50, 780, "Definition 1 Osmosis: The movement of water across a permeable membrane.")
            document.showPage()
        document.save()
        return SimpleUploadedFile("study.pdf", buffer.getvalue(), content_type="application/pdf")

    def scan(self, pages, *, subject=None, requested=None):
        return self.client.post(reverse("definition_pdf_lab", args=[(subject or self.subject).pk]), {
            "pdf_file": self.pdf_upload(pages), "start_page": "1",
            "pages_to_scan": str(requested if requested is not None else pages),
        })

    def test_grow_export_limit_is_shared_between_subjects_and_cannot_be_bypassed(self):
        with patch("dashboard.summary_export._build_pdf", return_value=b"%PDF-test"):
            for subject in (self.subject, self.second):
                response = self.client.get(reverse("download_subject_summary", args=[subject.pk]))
                self.assertEqual(response["Content-Type"], "application/pdf")
            response = self.client.get(reverse("download_subject_summary", args=[self.subject.pk]), {"organize": "books"})
        self.assertRedirects(response, reverse("my_plan"), fetch_redirect_response=False)
        self.assertEqual(get_pdf_usage(self.user)["pdf_exports"], 2)
        self.assertContains(self.client.get(reverse("my_plan")), "used your 2 PDF exports")

    def test_invalid_export_and_other_users_subject_do_not_use_allowance(self):
        self.assertEqual(self.client.get(reverse("download_subject_summary", args=[self.subject.pk]), {"organize": "bad"}).status_code, 400)
        other = get_user_model().objects.create_user(username="other-pdf-student")
        private = Subject.objects.create(user=other, name="Private")
        self.assertEqual(self.client.get(reverse("download_subject_summary", args=[private.pk])).status_code, 404)
        self.assertFalse(StudyMonthlyUsage.objects.filter(user=self.user).exists())

    def test_failed_export_does_not_use_allowance(self):
        with patch("dashboard.summary_export._build_pdf", side_effect=RuntimeError("Rendering failed")):
            with self.assertRaises(RuntimeError):
                self.client.get(reverse("download_subject_summary", args=[self.subject.pk]))
        self.assertEqual(get_pdf_usage(self.user)["pdf_exports"], 0)

    def test_grow_can_scan_five_pages_across_uploads_and_then_import_suggestions(self):
        self.assertEqual(self.scan(3).status_code, 200)
        response = self.scan(2, subject=self.second)
        self.assertEqual(response.status_code, 200)
        scan_id = response.context["scan_id"]
        self.assertEqual(get_pdf_usage(self.user)["summary_pages"], 5)
        rejected = self.scan(1)
        self.assertContains(rejected, "0 Auto Summarize pages remaining")
        self.assertEqual(get_pdf_usage(self.user)["summary_pages"], 5)
        response = self.client.post(reverse("definition_pdf_lab", args=[self.second.pk]), {
            "action": "add_one", "scan_id": scan_id, "candidate_index": "0",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Definition.objects.filter(knowledge_unit__subject=self.second).count(), 1)
        self.assertEqual(get_pdf_usage(self.user)["summary_pages"], 5)

    def test_remaining_page_limit_is_checked_before_extraction(self):
        self.scan(4)
        with patch("dashboard.pdf_lab_views.scan_page_images") as image_scan:
            response = self.scan(2)
        self.assertContains(response, "1 Auto Summarize pages remaining")
        image_scan.assert_not_called()
        self.assertEqual(get_pdf_usage(self.user)["summary_pages"], 4)

    def test_grow_can_edit_processed_suggestions_after_using_its_page_allowance(self):
        response = self.scan(5)
        scan_id = response.context["scan_id"]
        response = self.client.get(reverse("create_definition", args=[self.subject.pk]), {
            "pdf_scan_id": scan_id, "pdf_candidate_index": "0",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Osmosis")
        self.assertEqual(get_pdf_usage(self.user)["summary_pages"], 5)

    def test_only_actual_pages_are_counted_when_range_reaches_end_of_pdf(self):
        response = self.scan(2, requested=5)
        self.assertEqual(response.context["scan"]["pages_scanned"], 2)
        self.assertEqual(get_pdf_usage(self.user)["summary_pages"], 2)

    def test_invalid_pdf_does_not_use_allowance(self):
        response = self.client.post(reverse("definition_pdf_lab", args=[self.subject.pk]), {
            "pdf_file": SimpleUploadedFile("bad.pdf", b"%PDF-broken", content_type="application/pdf"),
            "start_page": "1", "pages_to_scan": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_pdf_usage(self.user)["summary_pages"], 0)

    def test_bloom_can_export_and_scan_above_grow_limits(self):
        StudyMembership.objects.filter(user=self.user).update(tier=StudyTier.BLOOM)
        with patch("dashboard.summary_export._build_pdf", return_value=b"%PDF-test"):
            for _ in range(3):
                self.assertEqual(self.client.get(reverse("download_subject_summary", args=[self.subject.pk])).status_code, 200)
        response = self.scan(6)
        self.assertEqual(response.context["scan"]["pages_scanned"], 6)
        self.assertIsNone(get_pdf_usage(self.user)["pages_remaining"])

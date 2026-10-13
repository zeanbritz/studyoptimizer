from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from learning.models import Definition, KnowledgeUnit, Subject

from .definition_detection import find_definition_candidates
from .pdf_lab_session import SESSION_KEY


class DefinitionDetectionTests(SimpleTestCase):
    def test_explicit_colon_and_label_patterns(self):
        text = (
            "Definitions\n"
            "Photosynthesis: The process by which plants turn light into energy.\n"
            "Definition 2.1 Velocity: The speed of an object in a particular direction."
        )
        candidates = find_definition_candidates(text, 7)
        self.assertEqual([item["term"] for item in candidates], ["Photosynthesis", "Velocity"])
        self.assertEqual([item["page"] for item in candidates], [7, 7])
        self.assertTrue(all(item["confidence"] == "strong" for item in candidates))

    def test_heading_and_sentence_patterns(self):
        heading = find_definition_candidates(
            "Definition\nGravity\nThe attractive force between objects with mass.", 2
        )
        sentence = find_definition_candidates(
            "Osmosis is the movement of water across a selectively permeable membrane.", 3
        )
        self.assertEqual(heading[0]["term"], "Gravity")
        self.assertEqual(heading[0]["confidence"], "strong")
        self.assertEqual(sentence[0]["term"], "Osmosis")
        self.assertEqual(sentence[0]["confidence"], "possible")

    def test_does_not_treat_common_headings_as_definitions(self):
        self.assertEqual(
            find_definition_candidates(
                "Chapter 1: An introduction to the theory of motion and energy.\n"
                "Example 2: A complete worked solution for the student to follow.", 1
            ),
            [],
        )


class DefinitionPdfLabTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.admin = users.objects.create_superuser(
            username="pdf_admin", email="admin@example.com", password="Safe-test-password-123!"
        )
        self.student = users.objects.create_user(
            username="pdf_student", password="Safe-test-password-123!"
        )
        self.subject = Subject.objects.create(user=self.admin, name="Biology")
        self.student_subject = Subject.objects.create(user=self.student, name="Maths")
        self.url = reverse("definition_pdf_lab", args=[self.subject.pk])
        self.client.force_login(self.admin)
        session = self.client.session
        session["onboarding_profile"] = {"name": "Admin"}
        session["onboarding_subjects"] = [
            {"name": self.subject.name, "database_id": self.subject.pk}
        ]
        session.save()

    @staticmethod
    def pdf_upload(lines_by_page):
        buffer = BytesIO()
        document = canvas.Canvas(buffer, pageCompression=0)
        for lines in lines_by_page:
            for index, line in enumerate(lines):
                document.drawString(50, 780 - index * 22, line)
            document.showPage()
        document.save()
        return SimpleUploadedFile(
            "biology-chapter.pdf", buffer.getvalue(), content_type="application/pdf"
        )

    def scan_definitions(self, lines=None):
        response = self.client.post(self.url, {
            "pdf_file": self.pdf_upload([lines or [
                "Definition 1 Photosynthesis: The process by which plants use light to make food.",
                "Definition 2 Osmosis: The movement of water through a selectively permeable membrane.",
            ]]),
            "start_page": "1",
            "pages_to_scan": "1",
        })
        self.assertEqual(response.status_code, 200)
        return self.client.session[SESSION_KEY]["id"]

    def test_superuser_can_preview_candidates_with_correct_pdf_pages(self):
        upload = self.pdf_upload([
            ["Definitions", "Photosynthesis: The process by which plants use light to make food."],
            ["Definition 2.1 Osmosis: The movement of water", "across a permeable membrane."],
        ])
        response = self.client.post(self.url, {
            "pdf_file": upload, "start_page": "1", "pages_to_scan": "2",
        })
        self.assertEqual(response.status_code, 200)
        scan = response.context["scan"]
        self.assertEqual(scan["total_pages"], 2)
        self.assertEqual(scan["text_pages"], 2)
        self.assertEqual(
            [(item["term"], item["page"]) for item in scan["candidates"]],
            [("Photosynthesis", 1), ("Osmosis", 2)],
        )
        self.assertContains(response, "Photosynthesis")
        self.assertEqual(KnowledgeUnit.objects.count(), 0)
        self.assertEqual(Definition.objects.count(), 0)

    def test_can_scan_later_page_range(self):
        upload = self.pdf_upload([
            ["Force: A push or pull that changes how an object moves."],
            ["Mass: The amount of matter contained within an object."],
        ])
        response = self.client.post(self.url, {
            "pdf_file": upload, "start_page": "2", "pages_to_scan": "1",
        })
        self.assertEqual(
            [item["term"] for item in response.context["scan"]["candidates"]],
            ["Mass"],
        )

    def test_scanned_pdf_without_text_explains_ocr_limit(self):
        response = self.client.post(self.url, {
            "pdf_file": self.pdf_upload([[]]),
            "start_page": "1", "pages_to_scan": "1",
        })
        self.assertEqual(response.context["scan"]["text_pages"], 0)
        self.assertContains(response, "OCR will be needed")

    def test_invalid_file_and_range_show_errors(self):
        invalid = SimpleUploadedFile("notes.txt", b"not a pdf", content_type="text/plain")
        response = self.client.post(self.url, {
            "pdf_file": invalid, "start_page": "1", "pages_to_scan": "1",
        })
        self.assertContains(response, "Choose a .pdf file")
        response = self.client.post(self.url, {
            "pdf_file": self.pdf_upload([["hello"]]),
            "start_page": "1", "pages_to_scan": "51",
        })
        self.assertContains(response, "scan 1-50 pages")
        response = self.client.post(self.url, {
            "pdf_file": self.pdf_upload([["hello"]]),
            "start_page": "2", "pages_to_scan": "1",
        })
        self.assertContains(response, "Start page must be between 1 and 1")

    def test_password_protected_pdf_is_rejected(self):
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.encrypt("secret")
        buffer = BytesIO()
        writer.write(buffer)
        response = self.client.post(self.url, {
            "pdf_file": SimpleUploadedFile("protected.pdf", buffer.getvalue()),
            "start_page": "1", "pages_to_scan": "1",
        })
        self.assertContains(response, "Password-protected PDFs are not supported")

    def test_student_cannot_view_lab_or_button(self):
        self.client.force_login(self.student)
        session = self.client.session
        session["onboarding_profile"] = {"name": "Student"}
        session["onboarding_subjects"] = [
            {"name": self.student_subject.name, "database_id": self.student_subject.pk}
        ]
        session.save()
        student_url = reverse("definition_pdf_lab", args=[self.student_subject.pk])
        self.assertEqual(self.client.get(student_url).status_code, 404)
        self.assertEqual(self.client.post(student_url).status_code, 404)
        page = self.client.get(reverse("subject_detail", args=[0]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Find definitions in PDF")

    def test_superuser_cannot_scan_another_users_subject(self):
        response = self.client.get(reverse("definition_pdf_lab", args=[self.student_subject.pk]))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_visitor_is_redirected(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_superuser_sees_button_on_subject_page(self):
        page = self.client.get(reverse("subject_detail", args=[0]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Find definitions in PDF")
        self.assertContains(page, self.url)

    def test_add_one_creates_reviewable_definition_and_cannot_duplicate(self):
        scan_id = self.scan_definitions()
        data = {"action": "add_one", "scan_id": scan_id, "candidate_index": "0"}
        response = self.client.post(self.url, data)
        self.assertRedirects(response, self.url)
        definition = Definition.objects.get(term="Photosynthesis")
        self.assertEqual(definition.knowledge_unit.subject, self.subject)
        self.assertEqual(definition.knowledge_unit.knowledge_type, KnowledgeUnit.KnowledgeType.DEFINITION)
        self.assertTrue(definition.knowledge_unit.active)
        self.assertContains(self.client.get(self.url), "Edit saved definition")
        self.client.post(self.url, data)
        self.assertEqual(Definition.objects.count(), 1)

    def test_add_all_skips_previously_added_and_exact_existing_definitions(self):
        scan_id = self.scan_definitions()
        self.client.post(self.url, {
            "action": "add_one", "scan_id": scan_id, "candidate_index": "0",
        })
        response = self.client.post(self.url, {"action": "add_all", "scan_id": scan_id})
        self.assertRedirects(response, self.url)
        self.assertEqual(Definition.objects.count(), 2)
        self.assertEqual(KnowledgeUnit.objects.filter(subject=self.subject).count(), 2)
        self.client.post(self.url, {"action": "add_all", "scan_id": scan_id})
        self.assertEqual(Definition.objects.count(), 2)

        new_scan_id = self.scan_definitions()
        self.client.post(self.url, {"action": "add_all", "scan_id": new_scan_id})
        self.assertEqual(Definition.objects.count(), 2)

    def test_edit_before_adding_prefills_existing_editor_then_saves_correction(self):
        scan_id = self.scan_definitions()
        editor_url = reverse("create_definition", args=[self.subject.pk])
        response = self.client.get(editor_url, {
            "subject_index": "0", "pdf_scan_id": scan_id, "pdf_candidate_index": "0",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Photosynthesis")
        self.assertContains(response, "Review detected definition")
        self.assertEqual(Definition.objects.count(), 0)

        response = self.client.post(editor_url, {
            "subject_index": "0",
            "pdf_scan_id": scan_id,
            "pdf_candidate_index": "0",
            "term": "Photosynthesis",
            "definition": "A corrected description of energy conversion in plants.",
        })
        self.assertRedirects(response, self.url)
        definition = Definition.objects.get(term="Photosynthesis")
        self.assertEqual(definition.definition, "A corrected description of energy conversion in plants.")
        self.assertEqual(self.client.session[SESSION_KEY]["saved"]["0"], definition.pk)

        new_scan_id = self.scan_definitions()
        self.client.post(self.url, {"action": "add_all", "scan_id": new_scan_id})
        self.assertEqual(Definition.objects.filter(term="Photosynthesis").count(), 1)
        definition.refresh_from_db()
        self.assertEqual(definition.definition, "A corrected description of energy conversion in plants.")

    def test_stale_scan_or_invalid_candidate_cannot_be_imported(self):
        scan_id = self.scan_definitions()
        for data in (
            {"action": "add_all", "scan_id": "wrong"},
            {"action": "add_all"},
            {"action": "add_one", "scan_id": scan_id, "candidate_index": "999"},
            {"action": "add_one", "scan_id": scan_id, "candidate_index": "bad"},
        ):
            response = self.client.post(self.url, data)
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(response.context["error"])
        self.assertEqual(Definition.objects.count(), 0)

    def test_batch_import_is_atomic_when_a_candidate_is_invalid(self):
        scan_id = self.scan_definitions()
        session = self.client.session
        state = session[SESSION_KEY]
        state["scan"]["candidates"][1]["definition"] = ""
        session[SESSION_KEY] = state
        session.save()

        response = self.client.post(self.url, {"action": "add_all", "scan_id": scan_id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "incomplete")
        self.assertEqual(Definition.objects.count(), 0)
        self.assertEqual(KnowledgeUnit.objects.count(), 0)

    def test_other_users_subject_cannot_receive_imports(self):
        scan_id = self.scan_definitions()
        other_url = reverse("definition_pdf_lab", args=[self.student_subject.pk])
        response = self.client.post(other_url, {"action": "add_all", "scan_id": scan_id})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Definition.objects.count(), 0)

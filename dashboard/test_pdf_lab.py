import json
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from learning.models import (
    BulletList, Comparison, Definition, Formula, FormulaVariable,
    KnowledgeUnit, Note, StepList, Subject,
)

from .definition_detection import find_definition_candidates
from .formula_detection import equation_to_structure, find_formula_candidates
from .models import SubjectTextbook
from .pdf_lab_session import SESSION_KEY
from .structured_detection import (
    find_comparison_candidates, find_list_candidates,
    find_note_candidates, find_step_candidates,
)


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


class FormulaDetectionTests(SimpleTestCase):
    def test_short_equations_are_editable(self):
        candidates = find_formula_candidates(
            "DIFFUSION\nJ = -D (dC/dx)\nMEMBRANE\nP = D/L; |J| = P (C1 - C2)", 3
        )
        self.assertEqual(len(candidates), 3)
        self.assertEqual(candidates[0]["title"], "Diffusion (J)")
        self.assertEqual(candidates[0]["page"], 3)
        self.assertEqual(candidates[0]["structure"][0]["value"], "J")
        self.assertEqual(candidates[0]["structure"][0]["type"], "variable")

    def test_prose_and_complex_expressions_are_not_suggested(self):
        self.assertEqual(find_formula_candidates(
            "A solution has C = 5 because this is its starting value.\n"
            "C1 = 2; C2 = 3; therefore the answer is C = 5.\n"
            "a = b = c", 1,
        ), [])
        with self.assertRaises(ValueError):
            equation_to_structure("a = b = c")


class StructuredDetectionTests(SimpleTestCase):
    def test_sample_style_list_steps_note_and_comparison(self):
        page = (
            "Assumptions to check\n"
            "Mix each chamber thoroughly.\n"
            "The concentration difference stays steady.\n"
            "Worked method for estimating permeability\n"
            "1     Record the chamber concentrations\n"
            "      Use two samples.\n"
            "2     Calculate permeability\n"
            "      Divide diffusivity by thickness.\n"
            "Two transport mechanisms compared\n"
            "Feature          Passive diffusion          Carrier transport\n"
            "Driving force    Concentration difference          Coupled gradient\n"
            "Saturation       Not expected in this model     Often saturates\n"
            "Study note. Check the units before using the equations.\n"
        )
        lists = find_list_candidates(page, 2)
        steps = find_step_candidates(page, 2)
        notes = find_note_candidates(page, 2)
        comparisons = find_comparison_candidates(page, 2)
        self.assertEqual(len(lists), 1)
        self.assertEqual(len(lists[0]["items"]), 2)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["steps"][1]["text"], "Calculate permeability")
        self.assertEqual(len(notes), 1)
        self.assertEqual(len(comparisons), 1)
        self.assertEqual(comparisons[0]["columns"], ["Passive diffusion", "Carrier transport"])
        self.assertEqual(len(comparisons[0]["rows"]), 2)

    def test_unmarked_prose_is_not_a_structured_suggestion(self):
        prose = "An experiment can include several measurements.\nThese values may be compared later."
        self.assertEqual(find_list_candidates(prose, 1), [])
        self.assertEqual(find_step_candidates(prose, 1), [])
        self.assertEqual(find_note_candidates(prose, 1), [])
        self.assertEqual(find_comparison_candidates(prose, 1), [])


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

    def scan_formulas(self, book_name="", chapter=""):
        response = self.client.post(self.url, {
            "pdf_file": self.pdf_upload([[
                "DIFFUSION", "J = -D (dC/dx)",
                "MEMBRANE", "P = D/L", "|J| = P (C1 - C2)",
            ]]),
            "start_page": "1", "pages_to_scan": "1",
            "book_name": book_name, "chapter": chapter,
        })
        self.assertEqual(response.status_code, 200)
        return response, self.client.session[SESSION_KEY]["id"]

    @staticmethod
    def structured_pdf_upload():
        buffer = BytesIO()
        document = canvas.Canvas(buffer, pageCompression=0)
        y = 780

        def line(text, x=50, gap=22):
            nonlocal y
            document.drawString(x, y, text)
            y -= gap

        line("Assumptions to check")
        line("Mix each chamber thoroughly so the sample represents the whole chamber.")
        line("The concentration difference remains steady during measurement.")
        line("Worked method for estimating permeability")
        line("1     Record the chamber concentrations")
        line("Use two samples from the chambers.", x=70)
        line("2     Calculate permeability")
        line("Divide diffusivity by thickness.", x=70)
        line("Two transport mechanisms compared")
        document.drawString(50, y, "Feature")
        document.drawString(220, y, "Passive diffusion")
        document.drawString(410, y, "Carrier transport")
        y -= 22
        document.drawString(50, y, "Driving force")
        document.drawString(220, y, "Concentration difference")
        document.drawString(410, y, "Coupled gradient")
        y -= 22
        document.drawString(50, y, "Saturation")
        document.drawString(220, y, "Not expected")
        document.drawString(410, y, "Often saturates")
        y -= 22
        line("Study note. Check the units and assumptions before using these equations.")
        document.showPage()
        document.save()
        return SimpleUploadedFile("structured.pdf", buffer.getvalue(), content_type="application/pdf")

    def scan_structured(self, book_name="", chapter=""):
        response = self.client.post(self.url, {
            "pdf_file": self.structured_pdf_upload(),
            "start_page": "1", "pages_to_scan": "1",
            "book_name": book_name, "chapter": chapter,
        })
        self.assertEqual(response.status_code, 200)
        return response, self.client.session[SESSION_KEY]["id"]

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
        self.assertNotContains(page, "Scan PDF for learning items")

    def test_superuser_cannot_scan_another_users_subject(self):
        response = self.client.get(reverse("definition_pdf_lab", args=[self.student_subject.pk]))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_visitor_is_redirected(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_superuser_sees_button_on_subject_page(self):
        page = self.client.get(reverse("subject_detail", args=[0]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Scan PDF for learning items")
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

    def test_optional_book_and_chapter_are_applied_to_definitions(self):
        SubjectTextbook.objects.create(subject=self.subject, name="Science Reader", page_count=200)
        response = self.client.post(self.url, {
            "pdf_file": self.pdf_upload([[
                "Diffusion: The movement of particles from high to low concentration."
            ]]),
            "start_page": "1", "pages_to_scan": "1",
            "book_name": "Science Reader", "chapter": "Chapter 2",
        })
        self.assertContains(response, "Science Reader")
        scan_id = self.client.session[SESSION_KEY]["id"]
        editor = self.client.get(reverse("create_definition", args=[self.subject.pk]), {
            "pdf_scan_id": scan_id, "pdf_candidate_index": "0", "subject_index": "0",
        })
        self.assertEqual(editor.context["selected_book"], "Science Reader")
        self.assertEqual(editor.context["chapter"], "Chapter 2")
        self.client.post(self.url, {"action": "add_one", "scan_id": scan_id, "candidate_index": "0"})
        definition = Definition.objects.get(term="Diffusion")
        self.assertEqual((definition.book_name, definition.chapter), ("Science Reader", "Chapter 2"))

    def test_scan_rejects_book_from_another_subject(self):
        SubjectTextbook.objects.create(subject=self.student_subject, name="Private Book", page_count=100)
        response = self.client.post(self.url, {
            "pdf_file": self.pdf_upload([["J = D/L"]]),
            "start_page": "1", "pages_to_scan": "1", "book_name": "Private Book",
        })
        self.assertContains(response, "does not belong to this subject")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_formula_preview_and_individual_batch_import(self):
        response, scan_id = self.scan_formulas()
        self.assertEqual(len(response.context["scan"]["formula_candidates"]), 3)
        self.assertContains(response, "Add all formulas")
        self.client.post(self.url, {
            "action": "add_formula_one", "scan_id": scan_id, "candidate_index": "0",
        })
        formula = Formula.objects.get(knowledge_unit__title="Diffusion (J)")
        self.assertEqual(formula.knowledge_unit.subject, self.subject)
        self.assertEqual(json.loads(formula.structure)[0]["value"], "J")
        self.assertTrue(FormulaVariable.objects.filter(formula=formula, symbol="J").exists())
        self.assertContains(self.client.get(self.url), "Edit saved formula")
        self.client.post(self.url, {"action": "add_formula_all", "scan_id": scan_id})
        self.assertEqual(Formula.objects.count(), 3)
        self.client.post(self.url, {"action": "add_formula_all", "scan_id": scan_id})
        self.assertEqual(Formula.objects.count(), 3)
        _, new_scan_id = self.scan_formulas()
        self.client.post(self.url, {"action": "add_formula_all", "scan_id": new_scan_id})
        self.assertEqual(Formula.objects.count(), 3)

    def test_formula_editor_prefills_context_and_returns_to_scan(self):
        SubjectTextbook.objects.create(subject=self.subject, name="Science Reader", page_count=200)
        _, scan_id = self.scan_formulas("Science Reader", "Chapter 2")
        editor_url = reverse("create_formula", args=[self.subject.pk])
        response = self.client.get(editor_url, {
            "pdf_scan_id": scan_id, "pdf_formula_index": "0", "subject_index": "0",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Review detected formula")
        self.assertEqual(response.context["selected_book"], "Science Reader")
        self.assertEqual(response.context["chapter"], "Chapter 2")
        self.assertEqual(json.loads(response.context["formula_structure"])[0]["value"], "J")
        response = self.client.post(editor_url, {
            "subject_index": "0", "pdf_scan_id": scan_id, "pdf_formula_index": "0",
            "title": "Corrected diffusion law", "formula_structure": response.context["formula_structure"],
            "book_name": "Science Reader", "chapter": "Chapter 2",
        })
        self.assertRedirects(response, self.url)
        formula = Formula.objects.get(knowledge_unit__title="Corrected diffusion law")
        self.assertEqual((formula.book_name, formula.chapter), ("Science Reader", "Chapter 2"))
        self.assertEqual(self.client.session[SESSION_KEY]["saved_formulas"]["0"], formula.pk)

    def test_formula_batch_inherits_selected_book_and_chapter(self):
        SubjectTextbook.objects.create(subject=self.subject, name="Science Reader", page_count=200)
        _, scan_id = self.scan_formulas("Science Reader", "Chapter 2")
        self.client.post(self.url, {"action": "add_formula_all", "scan_id": scan_id})
        self.assertEqual(Formula.objects.count(), 3)
        self.assertEqual(
            Formula.objects.filter(book_name="Science Reader", chapter="Chapter 2").count(),
            3,
        )

    def test_formula_batch_is_atomic_and_rejects_stale_scan(self):
        _, scan_id = self.scan_formulas()
        response = self.client.post(self.url, {"action": "add_formula_all", "scan_id": "stale"})
        self.assertContains(response, "no longer available")
        session = self.client.session
        state = session[SESSION_KEY]
        state["scan"]["formula_candidates"][1]["equation"] = "a = b = c"
        session[SESSION_KEY] = state
        session.save()
        response = self.client.post(self.url, {"action": "add_formula_all", "scan_id": scan_id})
        self.assertContains(response, "manual entry")
        self.assertEqual(Formula.objects.count(), 0)

    def test_structured_preview_uses_collapsed_count_cards(self):
        response, _ = self.scan_structured()
        scan = response.context["scan"]
        for key in ("list_candidates", "step_candidates", "note_candidates", "comparison_candidates"):
            self.assertEqual(len(scan[key]), 1, key)
        self.assertContains(response, 'class="result-group kind-list"')
        self.assertContains(response, 'class="result-group kind-comparison"')
        self.assertContains(response, "1 detected")
        self.assertContains(response, "Image-only PDFs need OCR")
        self.assertNotContains(response, "For a long textbook, scan one chapter at a time")

    def test_structured_items_can_be_added_individually_and_in_batches(self):
        SubjectTextbook.objects.create(subject=self.subject, name="Science Reader", page_count=200)
        _, scan_id = self.scan_structured("Science Reader", "Chapter 4")
        self.assertRedirects(self.client.post(self.url, {
            "action": "add_list_one", "scan_id": scan_id, "candidate_index": "0",
        }), self.url)
        for kind in ("list", "steps", "note", "comparison"):
            self.assertRedirects(self.client.post(self.url, {
                "action": f"add_{kind}_all", "scan_id": scan_id,
            }), self.url)
        self.assertEqual(BulletList.objects.count(), 1)
        self.assertEqual(BulletList.objects.get().items.count(), 2)
        self.assertEqual(StepList.objects.count(), 1)
        self.assertEqual(StepList.objects.get().steps.count(), 2)
        self.assertEqual(Note.objects.count(), 1)
        self.assertEqual(Comparison.objects.count(), 1)
        self.assertEqual(Comparison.objects.get().columns.count(), 2)
        self.assertEqual(Comparison.objects.get().rows.count(), 2)
        for model in (BulletList, StepList, Note, Comparison):
            self.assertEqual(model.objects.get().book_name, "Science Reader")
            self.assertEqual(model.objects.get().chapter, "Chapter 4")
        self.assertContains(self.client.get(self.url), "Edit saved comparison")
        _, new_scan_id = self.scan_structured("Science Reader", "Chapter 4")
        for kind in ("list", "steps", "note", "comparison"):
            self.client.post(self.url, {"action": f"add_{kind}_all", "scan_id": new_scan_id})
        self.assertEqual((BulletList.objects.count(), StepList.objects.count(), Note.objects.count(), Comparison.objects.count()), (1, 1, 1, 1))

    def test_structured_editor_can_correct_each_type_before_adding(self):
        _, scan_id = self.scan_structured()
        cases = {
            "list": {
                "title": "Corrected assumptions", "entry_text": ["First item", "Second item"],
                "entry_description": ["", ""],
            },
            "steps": {
                "title": "Corrected method", "entry_text": ["First step", "Second step"],
                "entry_description": ["Check inputs", "Check output"],
            },
            "note": {"title": "Corrected note", "content": "A corrected note with enough detail."},
            "comparison": {
                "title": "Corrected comparison", "column_name": ["Option A", "Option B"],
                "row_name": ["Speed"], "cell_left": ["Slow"], "cell_right": ["Fast"],
            },
        }
        for kind, changes in cases.items():
            editor = reverse("edit_pdf_suggestion", args=[self.subject.pk, kind, 0])
            preview = self.client.get(editor, {"scan_id": scan_id})
            self.assertEqual(preview.status_code, 200)
            self.assertContains(preview, "Review detected")
            response = self.client.post(editor, {"scan_id": scan_id, **changes})
            self.assertRedirects(response, self.url)
            self.assertIn("0", self.client.session[SESSION_KEY][{
                "list": "saved_lists", "steps": "saved_steps",
                "note": "saved_notes", "comparison": "saved_comparisons",
            }[kind]])
        self.assertEqual(BulletList.objects.get().question, "Corrected assumptions")
        self.assertEqual(StepList.objects.get().steps.first().description, "Check inputs")
        self.assertEqual(Note.objects.get().content, "A corrected note with enough detail.")
        self.assertEqual(Comparison.objects.get().columns.first().name, "Option A")

    def test_structured_import_rejects_stale_scan_and_is_atomic(self):
        _, scan_id = self.scan_structured()
        response = self.client.post(self.url, {"action": "add_list_all", "scan_id": "stale"})
        self.assertContains(response, "no longer available")
        session = self.client.session
        state = session[SESSION_KEY]
        state["scan"]["list_candidates"].append({"title": "Broken", "items": []})
        session[SESSION_KEY] = state
        session.save()
        response = self.client.post(self.url, {"action": "add_list_all", "scan_id": scan_id})
        self.assertContains(response, "needs between 1 and 20 entries")
        self.assertEqual(BulletList.objects.count(), 0)
        self.assertEqual(KnowledgeUnit.objects.count(), 0)

    def test_structured_editor_is_private_and_subject_scoped(self):
        _, scan_id = self.scan_structured()
        editor = reverse("edit_pdf_suggestion", args=[self.subject.pk, "list", 0])
        self.assertEqual(self.client.get(editor, {"scan_id": "stale"}).status_code, 302)
        self.assertEqual(self.client.get(reverse(
            "edit_pdf_suggestion", args=[self.student_subject.pk, "list", 0],
        ), {"scan_id": scan_id}).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(editor, {"scan_id": scan_id}).status_code, 404)

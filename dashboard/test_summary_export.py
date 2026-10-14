import json
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from learning.models import (
    BulletItem, BulletList, Comparison, ComparisonCell, ComparisonColumn,
    ComparisonRow, Definition, Formula, KnowledgeUnit, Note, StepItem, StepList,
    Subject,
)

from .summary_export import (
    TYPE_ORDER, _collect_items, _formula_text, _group_by_book_and_chapter,
    _natural_sort_key,
)


class SubjectSummaryExportTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.student = user_model.objects.create_user(
            username="summary_student", password="Safe-test-password-123!"
        )
        self.other_student = user_model.objects.create_user(
            username="other_student", password="Safe-test-password-123!"
        )
        self.subject = Subject.objects.create(user=self.student, name="Physics & Maths")
        self.other_subject = Subject.objects.create(
            user=self.other_student, name="Private Biology"
        )
        self.url = reverse("download_subject_summary", args=[self.subject.pk])
        self.client.force_login(self.student)

    def add_unit(self, kind, title):
        return KnowledgeUnit.objects.create(
            subject=self.subject, knowledge_type=kind, title=title
        )

    def test_exports_are_pdf_downloads_in_both_organizations(self):
        unit = self.add_unit(KnowledgeUnit.KnowledgeType.DEFINITION, "Force")
        Definition.objects.create(
            knowledge_unit=unit, term="Force", definition="Mass times acceleration.",
            book_name="Mechanics", chapter="Chapter 1",
        )
        for mode in ("regular", "books"):
            with self.subTest(mode=mode):
                response = self.client.get(self.url, {"organize": mode})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/pdf")
                self.assertIn("attachment;", response["Content-Disposition"])
                self.assertTrue(response.content.startswith(b"%PDF-"))
                self.assertTrue(PdfReader(BytesIO(response.content)).pages[0].images.keys())

    def test_all_study_types_are_collected(self):
        definition_unit = self.add_unit(KnowledgeUnit.KnowledgeType.DEFINITION, "Energy")
        Definition.objects.create(
            knowledge_unit=definition_unit, term="Energy", definition="Capacity for work",
            book_name="Mechanics", chapter="Chapter 1",
        )
        formula_unit = self.add_unit(KnowledgeUnit.KnowledgeType.FORMULA, "Newton's law")
        Formula.objects.create(
            knowledge_unit=formula_unit, structure=json.dumps([
                {"type": "variable", "value": "F"},
                {"type": "operator", "value": "="},
                {"type": "variable", "value": "m"},
                {"type": "operator", "value": "×"},
                {"type": "variable", "value": "a"},
            ]), book_name="Mechanics", chapter="Chapter 1",
        )
        list_unit = self.add_unit(KnowledgeUnit.KnowledgeType.BULLET_LIST, "Forces")
        bullet_list = BulletList.objects.create(
            knowledge_unit=list_unit, question="Forces", book_name="Mechanics",
            chapter="Chapter 1",
        )
        BulletItem.objects.create(bullet_list=bullet_list, text="Gravity", order=1)
        steps_unit = self.add_unit(KnowledgeUnit.KnowledgeType.STEPS, "Method")
        step_list = StepList.objects.create(knowledge_unit=steps_unit, question="Method")
        StepItem.objects.create(step_list=step_list, text="Measure", order=1)
        comparison_unit = self.add_unit(
            KnowledgeUnit.KnowledgeType.COMPARISON, "Mass versus weight"
        )
        comparison = Comparison.objects.create(
            knowledge_unit=comparison_unit, name="Mass versus weight"
        )
        column = ComparisonColumn.objects.create(
            comparison=comparison, name="Mass", order=1
        )
        row = ComparisonRow.objects.create(comparison=comparison, name="Unit", order=1)
        ComparisonCell.objects.create(row=row, column=column, content="kg")
        Note.objects.create(
            subject=self.subject, title="Reminder", content="Revise",
            book_name="Mechanics",
        )
        hidden = self.add_unit(KnowledgeUnit.KnowledgeType.DEFINITION, "Inactive")
        hidden.active = False
        hidden.save(update_fields=["active"])
        Definition.objects.create(knowledge_unit=hidden, term="Inactive", definition="Hidden")

        items = _collect_items(self.subject)
        self.assertEqual(
            {item["kind"] for item in items},
            {kind for kind, _, _ in TYPE_ORDER},
        )
        self.assertEqual(len(items), 6)
        self.assertIn("F = m × a", next(item for item in items if item["kind"] == "FORMULA")["body"])
        books, extra = _group_by_book_and_chapter(items)
        self.assertEqual(len(books["Mechanics"]["Chapter 1"]), 3)
        self.assertEqual(len(extra), 3)
        self.assertIn("Reminder", {item["title"] for item in extra})
        self.assertEqual(
            next(item for item in items if item["kind"] == "COMPARISON")["details"],
            [("Unit", "Mass: kg")],
        )

    def test_nested_fraction_is_readable_not_raw_json(self):
        structure = json.dumps([
            {"type": "variable", "value": "a"},
            {"type": "operator", "value": "="},
            {"type": "fraction", "numerator": [{"type": "variable", "value": "Δv"}],
             "denominator": [{"type": "variable", "value": "Δt"}]},
        ])
        self.assertEqual(_formula_text(structure), "a = (Δv) / (Δt)")

    def test_chapters_sort_in_human_order(self):
        self.assertEqual(
            sorted(["Chapter 10", "Chapter 2", "Chapter 1"], key=_natural_sort_key),
            ["Chapter 1", "Chapter 2", "Chapter 10"],
        )

    def test_obvious_chapter_number_variants_share_one_heading(self):
        items = [
            {"book": "Biology", "chapter": name, "title": name}
            for name in ("2", "chapter2", "chapter 2", "Chapter 2: Cells")
        ] + [
            {"book": "Biology", "chapter": "Chapter 20", "title": "Other chapter"},
            {"book": "Chemistry", "chapter": "2", "title": "Other book"},
        ]
        books, extra = _group_by_book_and_chapter(items)
        self.assertEqual(extra, [])
        self.assertEqual(len(books["Biology"]), 2)
        self.assertEqual(len(books["Biology"]["Chapter 2: Cells"]), 4)
        self.assertEqual(len(books["Biology"]["Chapter 20"]), 1)
        self.assertEqual(len(books["Chemistry"]["Chapter 2"]), 1)

    def test_empty_subject_still_exports(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_other_students_subject_is_not_accessible(self):
        response = self.client.get(
            reverse("download_subject_summary", args=[self.other_subject.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_anonymous_user_must_sign_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_invalid_mode_and_post_are_rejected(self):
        self.assertEqual(self.client.get(self.url, {"organize": "other"}).status_code, 400)
        self.assertEqual(self.client.post(self.url).status_code, 405)

    def test_subject_page_shows_export_button_and_options(self):
        session = self.client.session
        session["onboarding_profile"] = {"name": "Student"}
        session["onboarding_subjects"] = [
            {"name": self.subject.name, "database_id": self.subject.pk}
        ]
        session.save()
        response = self.client.get(reverse("subject_detail", args=[0]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Download summary")
        self.assertContains(response, "Books &amp; chapters")
        self.assertContains(response, self.url)

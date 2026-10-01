from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from dashboard.models import SubjectTextbook

from .models import Definition, Formula, KnowledgeUnit, Subject


class CreateFormulaTests(TestCase):
    def setUp(self):
        self.student = get_user_model().objects.create_user(
            username="formula_student",
            password="Safe-test-password-123!",
        )
        self.subject = Subject.objects.create(
            user=self.student,
            name="Mathematics",
        )
        self.client.force_login(self.student)

    def test_save_returns_to_originating_subject(self):
        response = self.client.post(
            reverse(
                "create_formula",
                kwargs={"subject_id": self.subject.id},
            ),
            {
                "subject_index": "2",
                "title": "Area of a circle",
                "formula_structure": "[]",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "subject_detail",
                kwargs={"subject_index": 2},
            ),
            fetch_redirect_response=False,
        )
        self.assertTrue(
            Formula.objects.filter(
                knowledge_unit__subject=self.subject,
                knowledge_unit__title="Area of a circle",
            ).exists()
        )


class DefinitionTextbookTests(TestCase):
    def setUp(self):
        self.student = get_user_model().objects.create_user(
            username="definition_student",
            password="Safe-test-password-123!",
        )
        self.subject = Subject.objects.create(
            user=self.student,
            name="Biology",
        )
        self.book = SubjectTextbook.objects.create(
            subject=self.subject,
            name="Biology Guide",
            page_count=180,
        )
        self.other_subject = Subject.objects.create(
            user=self.student,
            name="Chemistry",
        )
        SubjectTextbook.objects.create(
            subject=self.other_subject,
            name="Chemistry Guide",
            page_count=120,
        )
        self.client.force_login(self.student)
        self.create_url = reverse(
            "create_definition",
            kwargs={"subject_id": self.subject.pk},
        )

    def test_create_page_shows_only_subject_books_and_selects_sole_book(self):
        response = self.client.get(self.create_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Biology Guide")
        self.assertNotContains(response, "Chemistry Guide")
        self.assertEqual(response.context["selected_book"], "Biology Guide")

    def test_create_page_does_not_guess_when_subject_has_multiple_books(self):
        SubjectTextbook.objects.create(
            subject=self.subject,
            name="Biology Workbook",
            page_count=90,
        )

        response = self.client.get(self.create_url)

        self.assertContains(response, "Biology Workbook")
        self.assertEqual(response.context["selected_book"], "")

    def test_create_saves_selected_book_and_chapter(self):
        response = self.client.post(
            self.create_url,
            {
                "subject_index": "0",
                "term": "Cell",
                "definition": "The basic unit of life.",
                "book_name": self.book.name,
                "chapter": "Chapter 2",
            },
        )

        self.assertRedirects(
            response,
            reverse("subject_detail", kwargs={"subject_index": 0}),
            fetch_redirect_response=False,
        )
        definition = Definition.objects.get(term="Cell")
        self.assertEqual(definition.book_name, self.book.name)
        self.assertEqual(definition.chapter, "Chapter 2")

    def test_create_rejects_book_from_another_subject(self):
        response = self.client.post(
            self.create_url,
            {
                "term": "Cell",
                "definition": "The basic unit of life.",
                "book_name": "Chemistry Guide",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "does not belong to this subject")
        self.assertEqual(Definition.objects.count(), 0)
        self.assertEqual(KnowledgeUnit.objects.count(), 0)

    def test_edit_can_change_textbook_details(self):
        unit = KnowledgeUnit.objects.create(
            subject=self.subject,
            title="Cell",
            knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
        )
        definition = Definition.objects.create(
            knowledge_unit=unit,
            term="Cell",
            definition="The basic unit of life.",
            book_name=self.book.name,
            chapter="Chapter 2",
        )
        edit_url = reverse(
            "edit_definition",
            kwargs={"definition_id": definition.pk},
        )

        response = self.client.get(edit_url)
        self.assertEqual(response.context["selected_book"], self.book.name)

        response = self.client.post(
            edit_url,
            {
                "term": "Cell",
                "definition": "The basic unit of living things.",
                "book_name": "",
                "chapter": "Chapter 3",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "definition_list",
                kwargs={"subject_id": self.subject.pk},
            ),
            fetch_redirect_response=False,
        )
        definition.refresh_from_db()
        self.assertEqual(definition.book_name, "")
        self.assertEqual(definition.chapter, "Chapter 3")

    def test_edit_rejects_book_from_another_subject(self):
        unit = KnowledgeUnit.objects.create(
            subject=self.subject,
            title="Cell",
            knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
        )
        definition = Definition.objects.create(
            knowledge_unit=unit,
            term="Cell",
            definition="The basic unit of life.",
            book_name=self.book.name,
        )

        response = self.client.post(
            reverse(
                "edit_definition",
                kwargs={"definition_id": definition.pk},
            ),
            {
                "term": "Changed",
                "definition": "Changed definition.",
                "book_name": "Chemistry Guide",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "does not belong to this subject")
        definition.refresh_from_db()
        self.assertEqual(definition.term, "Cell")
        self.assertEqual(definition.book_name, self.book.name)

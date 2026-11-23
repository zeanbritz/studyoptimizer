import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from dashboard.models import SubjectTextbook

from .models import Definition, Formula, FormulaVariable, KnowledgeUnit, Subject


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

    def test_repeated_variables_share_one_saved_meaning(self):
        structure = [
            {"id": "first-l", "type": "variable", "value": "L", "meaning": ""},
            {"id": "equals", "type": "operator", "value": "=", "meaning": ""},
            {"id": "second-l", "type": "variable", "value": "L", "meaning": "Length"},
        ]
        response = self.client.post(
            reverse("create_formula", kwargs={"subject_id": self.subject.id}),
            {
                "subject_index": "0",
                "title": "Length rule",
                "formula_structure": json.dumps(structure),
            },
        )

        self.assertEqual(response.status_code, 302)
        formula = Formula.objects.get(knowledge_unit__title="Length rule")
        saved = json.loads(formula.structure)
        self.assertEqual(
            [item["meaning"] for item in saved if item["type"] == "variable"],
            ["Length", "Length"],
        )
        self.assertEqual(formula.variables.get(symbol="L").meaning, "Length")

    def test_pasted_formula_uses_the_pdf_formula_structure(self):
        response = self.client.post(
            reverse("parse_formula_structure"),
            data=json.dumps({"equation": "F = m*a²"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        structure = response.json()["structure"]
        self.assertEqual(
            [item["value"] for item in structure],
            ["F", "=", "m", "*", "a", "^", "2"],
        )
        self.assertEqual(structure[5]["type"], "operator")

    def test_create_formula_keeps_the_paste_dialog_closed_until_requested(self):
        response = self.client.get(
            reverse("create_formula", kwargs={"subject_id": self.subject.id})
        )

        self.assertContains(response, 'id="paste-formula-button"')
        self.assertContains(response, 'id="paste-formula-modal"')
        self.assertContains(response, "hidden")

    def test_pasted_formula_keeps_recognised_parts_of_an_ambiguous_equation(self):
        response = self.client.post(
            reverse("parse_formula_structure"),
            data=json.dumps({"equation": "a = b = c"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["value"] for item in response.json()["structure"]],
            ["a", "=", "b"],
        )
        self.assertTrue(response.json()["partial"])
        self.assertIn("skipped", response.json()["message"])


class FormulaDetailTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="formula_detail_student",
            password="Safe-test-password-123!",
        )
        subject = Subject.objects.create(user=user, name="Physics")
        unit = KnowledgeUnit.objects.create(
            subject=subject,
            title="Distance rule",
            knowledge_type=KnowledgeUnit.KnowledgeType.FORMULA,
        )
        self.formula = Formula.objects.create(knowledge_unit=unit)
        FormulaVariable.objects.create(
            formula=self.formula,
            symbol="d",
            meaning="Distance travelled",
            order=1,
        )
        FormulaVariable.objects.create(
            formula=self.formula,
            symbol="PVIFA(k,n)",
            meaning="",
            order=2,
        )
        self.client.force_login(user)

    def test_formula_detail_only_shows_described_symbols(self):
        response = self.client.get(reverse("formula_detail", args=[self.formula.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [variable.symbol for variable in response.context["variables"]],
            ["d"],
        )
        self.assertContains(response, "Distance travelled")
        self.assertNotContains(response, "No description")

    def test_edit_formula_uses_the_symbol_picker_instead_of_adding_a_bracket(self):
        response = self.client.get(reverse("edit_formula", args=[self.formula.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="picker-toggle"')
        self.assertContains(response, 'data-element-value="α"')
        self.assertContains(response, 'id="add-variable-button"')
        self.assertContains(response, 'id="add-fraction-button"')
        self.assertNotContains(response, "onclick=\"addElement('symbol', '(')\"")


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

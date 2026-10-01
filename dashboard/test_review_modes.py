import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from learning.models import (
    BulletItem,
    BulletList,
    Comparison,
    ComparisonCell,
    ComparisonColumn,
    ComparisonRow,
    Formula,
    KnowledgeUnit,
    Note,
    StepItem,
    StepList,
    StudentKnowledge,
    Subject,
)


class ReviewModesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="mode_student", password="Safe-test-password-123!"
        )
        self.subject = Subject.objects.create(user=self.user, name="Biology")
        self.other_subject = Subject.objects.create(user=self.user, name="Chemistry")
        self.client.force_login(self.user)

        def unit(title, kind):
            return KnowledgeUnit.objects.create(
                subject=self.subject, title=title, knowledge_type=kind
            )

        formula = Formula.objects.create(
            knowledge_unit=unit("Water", KnowledgeUnit.KnowledgeType.FORMULA),
            structure=json.dumps([{"type": "variable", "value": "H₂O"}]),
            purpose="Water formula purpose",
        )
        bullet_list = BulletList.objects.create(
            knowledge_unit=unit("Cell parts", KnowledgeUnit.KnowledgeType.BULLET_LIST),
            question="Name cell parts",
        )
        BulletItem.objects.create(bullet_list=bullet_list, text="Nucleus answer")
        step_list = StepList.objects.create(
            knowledge_unit=unit("Steps", KnowledgeUnit.KnowledgeType.STEPS),
            question="How to study",
        )
        StepItem.objects.create(step_list=step_list, text="Read answer")
        comparison = Comparison.objects.create(
            knowledge_unit=unit("Compare", KnowledgeUnit.KnowledgeType.COMPARISON),
            name="Cell comparison",
        )
        column = ComparisonColumn.objects.create(comparison=comparison, name="Plant")
        row = ComparisonRow.objects.create(comparison=comparison, name="Wall")
        ComparisonCell.objects.create(row=row, column=column, content="Has a cell wall")

        self.cases = (
            ("formula", formula, "review_formulas", "practice_formula", "Water formula purpose"),
            ("list", bullet_list, "review_lists", "review_list", "Nucleus answer"),
            ("step", step_list, "review_steps", "practice_step_review", "Read answer"),
            ("comparison", comparison, "review_comparisons", "practice_comparison_review", "Has a cell wall"),
        )

    def test_review_is_read_only_and_test_keeps_existing_links(self):
        for kind, item, list_name, test_name, answer in self.cases:
            with self.subTest(kind=kind):
                read_url = reverse(
                    "read_review_item", kwargs={"kind": kind, "item_id": item.pk}
                )
                review_page = self.client.get(reverse(list_name))
                self.assertEqual(review_page.status_code, 200)
                self.assertEqual(review_page.context["mode"], "review")
                self.assertContains(review_page, read_url)
                self.assertNotContains(review_page, 'id="random-review-button"')
                html = review_page.content.decode()
                self.assertLess(html.index('id="subject-filter"'), html.index('class="mode-switch"'))
                self.assertLess(html.index('class="mode-switch"'), html.index('class="review-list"'))

                reader = self.client.get(read_url)
                self.assertContains(reader, answer)
                self.assertContains(reader, "Finish Review")
                self.assertNotContains(reader, 'class="mode-switch"')
                self.assertEqual(StudentKnowledge.objects.count(), 0)
                test_page = self.client.get(reverse(list_name) + "?mode=test")
                self.assertEqual(test_page.context["mode"], "test")
                self.assertContains(test_page, 'id="random-review-button"')
                self.assertContains(test_page, reverse(test_name, args=[item.pk]))

    def test_reader_subject_scope_and_access_controls(self):
        other_user = get_user_model().objects.create_user(
            username="private_student", password="Safe-test-password-123!"
        )
        private_unit = KnowledgeUnit.objects.create(
            subject=Subject.objects.create(user=other_user, name="Private"),
            title="Private formula",
            knowledge_type=KnowledgeUnit.KnowledgeType.FORMULA,
        )
        private_formula = Formula.objects.create(knowledge_unit=private_unit)
        private_url = reverse(
            "read_review_item", kwargs={"kind": "formula", "item_id": private_formula.pk}
        )
        self.assertEqual(self.client.get(private_url).status_code, 404)

        formula = self.cases[0][1]
        formula_url = reverse("read_review_item", kwargs={"kind": "formula", "item_id": formula.pk})
        self.assertEqual(
            self.client.get(formula_url + f"?subject_id={self.other_subject.pk}").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(formula_url + f"?subject_id={self.subject.pk}").status_code,
            200,
        )
        next_unit = KnowledgeUnit.objects.create(
            subject=self.subject,
            title="Zzz formula",
            knowledge_type=KnowledgeUnit.KnowledgeType.FORMULA,
        )
        next_formula = Formula.objects.create(knowledge_unit=next_unit)
        other_unit = KnowledgeUnit.objects.create(
            subject=self.other_subject,
            title="Other subject formula",
            knowledge_type=KnowledgeUnit.KnowledgeType.FORMULA,
        )
        Formula.objects.create(knowledge_unit=other_unit)
        scoped = self.client.get(formula_url + f"?subject_id={self.subject.pk}")
        self.assertEqual(scoped.context["total"], 2)
        self.assertIn(str(next_formula.pk), scoped.context["next_url"])
        self.assertIn(f"subject_id={self.subject.pk}", scoped.context["next_url"])
        self.assertEqual(self.client.post(formula_url).status_code, 405)
        self.assertEqual(
            self.client.get(reverse("read_review_item", args=["unknown", formula.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("read_review_item", args=["note", formula.pk])).status_code,
            404,
        )

        inactive = KnowledgeUnit.objects.create(
            subject=self.subject,
            title="Inactive formula",
            knowledge_type=KnowledgeUnit.KnowledgeType.FORMULA,
            active=False,
        )
        hidden = Formula.objects.create(knowledge_unit=inactive)
        hidden_url = reverse("read_review_item", args=["formula", hidden.pk])
        self.assertEqual(self.client.get(hidden_url).status_code, 404)

    def test_notes_keep_the_original_single_review_flow(self):
        note = Note.objects.create(
            subject=self.subject, title="My note", content="Detailed note"
        )
        response = self.client.get(reverse("review_notes"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="mode-switch"')
        self.assertContains(response, "Random Review")
        self.assertContains(
            response,
            reverse("note_detail", args=[note.pk]) + "?mode=global_review",
        )

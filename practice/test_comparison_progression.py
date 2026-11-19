from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from learning.models import (
    Comparison,
    ComparisonCell,
    ComparisonColumn,
    ComparisonRow,
    KnowledgeUnit,
    StudentKnowledge,
    Subject,
)
from practice.views.comparisons import comparison_hidden_cell_count


class ComparisonDifficultyTests(SimpleTestCase):
    def test_missing_answers_increase_without_a_fully_blank_board_before_six(self):
        self.assertEqual(
            [comparison_hidden_cell_count(7, mastery) for mastery in range(7)],
            [1, 2, 3, 4, 5, 6, 7],
        )

    def test_smaller_comparisons_keep_a_revealed_answer_until_six(self):
        self.assertEqual(
            [comparison_hidden_cell_count(4, mastery) for mastery in range(7)],
            [1, 1, 2, 2, 3, 3, 4],
        )


class ComparisonReviewProgressionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="comparison-reviewer",
            password="test-pass",
            beta_lifetime_access=True,
        )
        self.subject = Subject.objects.create(user=self.user, name="Biology")
        self.knowledge_unit = KnowledgeUnit.objects.create(
            subject=self.subject,
            title="Cell transport comparison",
            knowledge_type=KnowledgeUnit.KnowledgeType.COMPARISON,
        )
        self.comparison = Comparison.objects.create(
            knowledge_unit=self.knowledge_unit,
            name="Transport methods",
        )
        row = ComparisonRow.objects.create(
            comparison=self.comparison,
            name="Key characteristics",
            order=1,
        )
        for order in range(1, 8):
            column = ComparisonColumn.objects.create(
                comparison=self.comparison,
                name=f"Method {order}",
                order=order,
            )
            ComparisonCell.objects.create(
                row=row,
                column=column,
                content=f"Characteristic {order}",
            )

        self.client.force_login(self.user)
        self.url = reverse("practice_comparison_review", args=[self.comparison.pk])

    def _revealed_cell_count(self, response):
        return sum(
            slot["revealed"] is not None
            for review_row in response.context["review_rows"]
            for slot in review_row["slots"]
        )

    def test_new_student_only_places_one_answer(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["shuffled_cells"]), 1)
        self.assertEqual(self._revealed_cell_count(response), 6)

    def test_mastery_six_requires_every_answer(self):
        StudentKnowledge.objects.create(
            student=self.user,
            knowledge_unit=self.knowledge_unit,
            mastery_level=6,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["shuffled_cells"]), 7)
        self.assertEqual(self._revealed_cell_count(response), 0)

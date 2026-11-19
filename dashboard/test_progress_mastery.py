from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from learning.models import KnowledgeUnit, StudentKnowledge, Subject


class ProgressMasteryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="progress-student",
            password="test-pass",
            beta_lifetime_access=True,
        )
        self.accounting = Subject.objects.create(
            user=self.user,
            name="Accounting",
        )
        self.biology = Subject.objects.create(
            user=self.user,
            name="Biology",
        )

        accounting_units = [
            KnowledgeUnit.objects.create(
                subject=self.accounting,
                title=f"Accounting item {number}",
                knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
            )
            for number in range(1, 4)
        ]
        biology_unit = KnowledgeUnit.objects.create(
            subject=self.biology,
            title="Biology item",
            knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
        )

        # The unreviewed third Accounting item intentionally has no progress
        # row, and therefore contributes zero of its six possible points.
        StudentKnowledge.objects.create(
            student=self.user,
            knowledge_unit=accounting_units[0],
            mastery_level=6,
        )
        StudentKnowledge.objects.create(
            student=self.user,
            knowledge_unit=accounting_units[1],
            mastery_level=3,
        )
        StudentKnowledge.objects.create(
            student=self.user,
            knowledge_unit=biology_unit,
            mastery_level=4,
        )
        self.client.force_login(self.user)

    def test_mastery_uses_average_item_mastery_levels(self):
        response = self.client.get(reverse("progress"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["overall_mastery"], 54)

        mastery_by_subject = {
            item["subject"].name: item["mastery"]
            for item in response.context["subject_progress"]
        }
        self.assertEqual(mastery_by_subject["Accounting"], 50)
        self.assertEqual(mastery_by_subject["Biology"], 67)

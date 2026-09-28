from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Formula, Subject


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

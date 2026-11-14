from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from learning.models import Definition, KnowledgeUnit, StudentKnowledge, Subject


class DefinitionMatchTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="definition_matcher",
            password="Safe-test-password-123!",
        )
        self.subject = Subject.objects.create(user=self.user, name="Business")
        self.definitions = [
            self.add_definition("Agency conflict", "A conflict between owners and managers."),
            self.add_definition("Liquidity", "The ability to meet short-term obligations."),
            self.add_definition("Equity", "The owners' residual interest in a business."),
            self.add_definition("Revenue", "Income earned from ordinary business activities."),
        ]
        self.client.force_login(self.user)

    def add_definition(self, term, text):
        unit = KnowledgeUnit.objects.create(
            subject=self.subject,
            title=term,
            knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
            active=True,
        )
        return Definition.objects.create(
            knowledge_unit=unit,
            term=term,
            definition=text,
        )

    def test_requires_four_definitions_in_the_selected_subject(self):
        small_subject = Subject.objects.create(user=self.user, name="Small")
        self.add_definition_to(small_subject, "One", "First definition.")
        self.add_definition_to(small_subject, "Two", "Second definition.")
        self.add_definition_to(small_subject, "Three", "Third definition.")

        response = self.client.get(
            reverse("practice_definition_match", args=[small_subject.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_correct_answer_marks_progress_and_reveals_all_choices(self):
        url = reverse("practice_definition_match", args=[self.subject.pk])
        question = self.client.get(
            url + "?activity=match&review_origin=library&review_mode=random"
        )

        self.assertEqual(question.status_code, 200)
        definition = question.context["definition"]
        response = self.client.post(
            url,
            {
                "question_token": question.context["question_token"],
                "selected_definition_id": definition.pk,
                "review_origin": "library",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["result"], "correct")
        self.assertContains(response, "Correct")
        self.assertContains(response, "is-correct")
        self.assertContains(response, "is-incorrect")

        progress = StudentKnowledge.objects.get(
            student=self.user,
            knowledge_unit=definition.knowledge_unit,
        )
        self.assertEqual(progress.review_count, 1)
        self.assertEqual(progress.correct_count, 1)
        self.assertEqual(progress.mastery_level, 1)

    def test_wrong_answer_marks_only_the_target_incorrect(self):
        url = reverse("practice_definition_match", args=[self.subject.pk])
        question = self.client.get(url + "?activity=match")
        definition = question.context["definition"]
        incorrect = next(
            option
            for option in question.context["options"]
            if option.pk != definition.pk
        )

        response = self.client.post(
            url,
            {
                "question_token": question.context["question_token"],
                "selected_definition_id": incorrect.pk,
            },
        )

        self.assertEqual(response.context["result"], "incorrect")
        self.assertContains(response, "Not quite")
        progress = StudentKnowledge.objects.get(
            student=self.user,
            knowledge_unit=definition.knowledge_unit,
        )
        self.assertEqual(progress.incorrect_count, 1)
        self.assertEqual(progress.mastery_level, 0)

    @patch("practice.views.definitions.random.choice")
    def test_random_entry_can_open_the_existing_drag_activity(self, choice):
        choice.side_effect = ["drag", self.definitions[0]]

        response = self.client.get(
            reverse("practice_definition_match", args=[self.subject.pk])
            + "?review_origin=library&review_mode=random"
        )

        self.assertRedirects(
            response,
            reverse("practice_definition_review", args=[self.definitions[0].pk])
            + "?review_scope=global&review_mode=random&review_origin=library",
            fetch_redirect_response=False,
        )

    def add_definition_to(self, subject, term, text):
        unit = KnowledgeUnit.objects.create(
            subject=subject,
            title=term,
            knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
            active=True,
        )
        return Definition.objects.create(
            knowledge_unit=unit,
            term=term,
            definition=text,
        )

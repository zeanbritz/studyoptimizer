from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from learning.models import Definition, KnowledgeUnit, StudentKnowledge, Subject


class DefinitionModesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="definition_reader", password="Safe-test-password-123!"
        )
        self.subject = Subject.objects.create(user=self.user, name="Biology")
        self.other_subject = Subject.objects.create(user=self.user, name="Chemistry")
        self.first = self.add_definition(self.subject, "Cells")
        self.second = self.add_definition(self.subject, "Tissues")
        self.third = self.add_definition(self.other_subject, "Atoms")
        self.client.force_login(self.user)

    def add_definition(self, subject, term, active=True):
        unit = KnowledgeUnit.objects.create(
            subject=subject,
            title=term,
            knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
            active=active,
        )
        return Definition.objects.create(
            knowledge_unit=unit,
            term=term,
            definition=f"Meaning of {term}.",
        )

    def test_review_mode_is_default_and_opens_read_only_definition(self):
        response = self.client.get(reverse("review_definitions"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["mode"], "review")
        self.assertContains(response, 'aria-current="page">Review</a>')
        self.assertNotContains(response, 'id="random-review-button"')
        self.assertContains(response, "Meaning of Cells.")
        self.assertContains(response, "Back to Review")
        self.assertNotContains(response, "← Back to Review")
        self.assertContains(
            response, reverse("read_definition", args=[self.first.pk])
        )

        response = self.client.get(reverse("read_definition", args=[self.first.pk]))
        self.assertContains(response, "Meaning of Cells.")
        self.assertContains(response, "Finish Review")
        self.assertNotContains(response, "All definitions")
        self.assertNotContains(response, 'class="mode-switch"')
        self.assertNotContains(response, "← Previous")
        self.assertNotContains(response, "Next →")
        self.assertEqual(StudentKnowledge.objects.count(), 0)

    def test_test_mode_keeps_existing_practice_links(self):
        response = self.client.get(reverse("review_definitions") + "?mode=test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["mode"], "test")
        self.assertContains(response, 'aria-current="page">Test</a>')
        self.assertContains(response, 'id="random-review-button"')
        self.assertNotContains(response, "Meaning of Cells.")
        self.assertContains(
            response,
            reverse("practice_definition_review", args=[self.first.pk])
            + "?review_scope=global",
        )

        quiz = self.client.get(
            reverse("practice_definition_review", args=[self.first.pk])
        )
        self.assertNotContains(quiz, 'class="mode-switch"')
        self.assertNotContains(quiz, reverse("read_definition", args=[self.first.pk]))

    def test_reader_browses_definitions_in_subject_without_writing_progress(self):
        url = reverse("read_definition", args=[self.first.pk])
        response = self.client.get(url + f"?subject_id={self.subject.pk}")
        self.assertEqual(response.context["position"], 1)
        self.assertEqual(response.context["total"], 2)
        self.assertIsNone(response.context["previous_url"])
        self.assertIn(str(self.second.pk), response.context["next_url"])
        self.assertNotIn(str(self.third.pk), response.context["next_url"])
        self.assertEqual(StudentKnowledge.objects.count(), 0)

    def test_reader_rejects_other_users_and_inactive_definitions(self):
        stranger = get_user_model().objects.create_user(
            username="other_reader", password="Safe-test-password-123!"
        )
        other = self.add_definition(
            Subject.objects.create(user=stranger, name="Private"), "Private"
        )
        inactive = self.add_definition(self.subject, "Hidden", active=False)
        for definition in (other, inactive):
            response = self.client.get(reverse("read_definition", args=[definition.pk]))
            self.assertEqual(response.status_code, 404)

    def test_reader_rejects_invalid_subject_scope_and_post(self):
        url = reverse("read_definition", args=[self.first.pk])
        self.assertEqual(
            self.client.get(url + f"?subject_id={self.other_subject.pk}").status_code,
            404,
        )
        self.assertEqual(self.client.post(url).status_code, 405)

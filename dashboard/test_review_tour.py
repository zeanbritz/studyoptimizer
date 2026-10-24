from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from dashboard.models import StudyProfile
from learning.models import KnowledgeUnit, StepItem, StepList, Subject


class ReviewTourTests(TestCase):
    category_routes = (
        "review_definitions",
        "review_formulas",
        "review_lists",
        "review_steps",
        "review_notes",
        "review_comparisons",
    )

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="review-tour-user",
            beta_lifetime_access=True,
        )
        self.profile = StudyProfile.objects.create(
            user=self.user,
            onboarding_complete=True,
        )
        self.client.force_login(self.user)

    def add_step(self):
        subject = Subject.objects.create(user=self.user, name="Physics")
        unit = KnowledgeUnit.objects.create(
            subject=subject,
            title="Measure acceleration",
            knowledge_type=KnowledgeUnit.KnowledgeType.STEPS,
        )
        step_list = StepList.objects.create(
            knowledge_unit=unit,
            question="How do I measure acceleration?",
        )
        StepItem.objects.create(step_list=step_list, order=1, text="Measure time")
        return step_list

    def test_tour_appears_in_whichever_review_category_is_opened_first(self):
        self.add_step()
        response = self.client.get(reverse("review_steps"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["show_review_tour"])
        self.assertContains(response, 'id="review-tour"')
        self.assertContains(response, "Review your saved material")
        self.assertContains(response, ">Test<")

    def test_empty_category_does_not_show_or_consume_the_tour(self):
        response = self.client.get(reverse("review_steps"))
        self.assertFalse(response.context["show_review_tour"])
        self.assertNotContains(response, 'id="review-tour"')
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.review_tour_completed)

        self.add_step()
        response = self.client.get(reverse("review_steps"))
        self.assertTrue(response.context["show_review_tour"])
        self.assertContains(response, 'id="review-tour"')

    def test_completing_tour_once_hides_it_from_all_six_categories(self):
        response = self.client.post(reverse("complete_review_tour"))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"success": True})
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.review_tour_completed)

        for route_name in self.category_routes:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertFalse(response.context["show_review_tour"])
                self.assertNotContains(response, 'id="review-tour"')

    def test_completion_endpoint_requires_post(self):
        response = self.client.get(reverse("complete_review_tour"))
        self.assertEqual(response.status_code, 405)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.review_tour_completed)

    def test_tour_completion_is_per_student(self):
        self.client.post(reverse("complete_review_tour"))
        other = get_user_model().objects.create_user(
            username="other-review-tour-user",
            beta_lifetime_access=True,
        )
        StudyProfile.objects.create(user=other, onboarding_complete=True)
        self.client.force_login(other)
        subject = Subject.objects.create(user=other, name="Chemistry")
        unit = KnowledgeUnit.objects.create(
            subject=subject,
            title="Titration",
            knowledge_type=KnowledgeUnit.KnowledgeType.STEPS,
        )
        StepList.objects.create(knowledge_unit=unit, question="How do I titrate?")
        response = self.client.get(reverse("review_steps"))
        self.assertTrue(response.context["show_review_tour"])
        self.assertContains(response, 'id="review-tour"')

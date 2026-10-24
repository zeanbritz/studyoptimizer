from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from dashboard.models import StudyProfile


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

    def test_tour_appears_in_whichever_review_category_is_opened_first(self):
        response = self.client.get(reverse("review_steps"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["show_review_tour"])
        self.assertContains(response, 'id="review-tour"')
        self.assertContains(response, "Review your saved material")
        self.assertContains(response, ">Test<")

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
        response = self.client.get(reverse("review_definitions"))
        self.assertTrue(response.context["show_review_tour"])
        self.assertContains(response, 'id="review-tour"')

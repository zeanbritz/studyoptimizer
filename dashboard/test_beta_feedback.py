from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import BetaFeedback


class BetaFeedbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="feedback_student",
            email="feedback@example.com",
            password="Safe-test-password-123!",
        )

    def setUp(self):
        self.url = reverse("submit_beta_feedback")
        self.client.force_login(self.user)

    @override_settings(BETA_FEEDBACK_ENABLED=True)
    def test_dashboard_shows_feedback_button(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="beta-feedback-launcher"')

    @override_settings(BETA_FEEDBACK_ENABLED=True)
    def test_feedback_is_saved_for_signed_in_user(self):
        response = self.client.post(
            self.url,
            {
                "category": "idea",
                "message": "  Add a study timer.  ",
                "page_path": "/dashboard/?private=value",
                "status": "resolved",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

        feedback = BetaFeedback.objects.get()
        self.assertEqual(feedback.user, self.user)
        self.assertEqual(feedback.category, "idea")
        self.assertEqual(feedback.message, "Add a study timer.")
        self.assertEqual(feedback.page_path, "/dashboard/")
        self.assertEqual(feedback.status, BetaFeedback.Status.NEW)

    @override_settings(BETA_FEEDBACK_ENABLED=True)
    def test_all_three_categories_are_accepted(self):
        for category in ("idea", "bug", "confusing"):
            with self.subTest(category=category):
                response = self.client.post(
                    self.url,
                    {"category": category, "message": "Test feedback"},
                )
                self.assertEqual(response.status_code, 200)

        self.assertEqual(BetaFeedback.objects.count(), 3)

    @override_settings(BETA_FEEDBACK_ENABLED=True)
    def test_invalid_feedback_is_rejected(self):
        invalid_entries = (
            {"category": "other", "message": "A message"},
            {"category": "bug", "message": "   "},
            {"category": "idea", "message": "x" * 2001},
        )

        for entry in invalid_entries:
            response = self.client.post(self.url, entry)
            self.assertEqual(response.status_code, 400)

        self.assertFalse(BetaFeedback.objects.exists())

    @override_settings(BETA_FEEDBACK_ENABLED=False)
    def test_off_switch_hides_button_and_blocks_submissions(self):
        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertNotContains(dashboard, 'id="beta-feedback-launcher"')

        response = self.client.post(
            self.url,
            {"category": "idea", "message": "Should not be saved"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(BetaFeedback.objects.exists())

    @override_settings(BETA_FEEDBACK_ENABLED=True)
    def test_anonymous_submission_is_blocked(self):
        self.client.logout()

        response = self.client.post(
            self.url,
            {"category": "bug", "message": "A problem"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(BetaFeedback.objects.exists())

    @override_settings(BETA_FEEDBACK_ENABLED=True)
    def test_csrf_token_is_required(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            self.url,
            {"category": "bug", "message": "A problem"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(BetaFeedback.objects.exists())

    @override_settings(BETA_FEEDBACK_ENABLED=True)
    def test_limit_of_ten_messages_per_hour(self):
        for _ in range(10):
            BetaFeedback.objects.create(
                user=self.user,
                category=BetaFeedback.Category.IDEA,
                message="Previous feedback",
            )

        response = self.client.post(
            self.url,
            {"category": "idea", "message": "One more"},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(BetaFeedback.objects.count(), 10)
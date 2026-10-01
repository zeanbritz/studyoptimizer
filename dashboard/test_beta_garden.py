from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class BetaGardenPreviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="gardener", password="test-password-123"
        )

    def test_garden_requires_login(self):
        response = self.client.get(reverse("beta_garden"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response.url)

    def test_garden_is_clearly_a_preview(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("beta_garden"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Experimental preview")
        self.assertContains(response, "It does not track missed days")
        self.assertContains(response, 'data-garden-state="resting"')
        self.assertContains(response, 'data-garden-state="visitors"')

    def test_todays_plan_links_to_garden(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("beta_garden"))
        self.assertContains(response, "Beta garden")

    def test_preview_does_not_accept_updates(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("beta_garden"), {"state": "visitors"})
        self.assertEqual(response.status_code, 405)

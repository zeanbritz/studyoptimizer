from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from learning.models import Subject


class SuperuserGardenTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="head-gardener", password="test-password-123"
        )
        self.student = get_user_model().objects.create_user(
            username="student-gardener", password="test-password-123"
        )

    def test_garden_requires_login(self):
        response = self.client.get(reverse("beta_garden"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response.url)

    def test_non_superuser_cannot_open_garden(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("beta_garden"))
        self.assertEqual(response.status_code, 403)

    def test_garden_has_phase_controls_without_preview_notices(self):
        Subject.objects.create(user=self.user, name="Biology")
        self.client.force_login(self.user)
        response = self.client.get(reverse("beta_garden"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Experimental preview")
        self.assertNotContains(response, "visual mockup")
        self.assertNotContains(response, "Preview only")
        self.assertContains(response, 'data-garden-state="resting"')
        self.assertContains(response, 'data-garden-state="visitors"')

    def test_garden_has_one_pot_per_owned_subject(self):
        mathematics = Subject.objects.create(user=self.user, name="Mathematics")
        history = Subject.objects.create(user=self.user, name="History")
        Subject.objects.create(user=self.student, name="Private subject")

        self.client.force_login(self.user)
        response = self.client.get(reverse("beta_garden"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="potplant potplant--', count=2)
        self.assertContains(response, "Mathematics")
        self.assertContains(response, "History")
        self.assertNotContains(response, "Private subject")
        self.assertContains(
            response,
            f'href="{reverse("subject_detail", args=[0])}" data-subject-id="{mathematics.pk}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("subject_detail", args=[1])}" data-subject-id="{history.pk}"',
        )

    def test_empty_garden_points_to_subjects(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("beta_garden"))
        self.assertContains(response, "Your first pot is waiting")
        self.assertContains(response, reverse("goals"))

    def test_todays_plan_only_shows_garden_to_superuser(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("beta_garden"))
        self.assertContains(response, "Open your garden")

        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("beta_garden"))

    def test_garden_does_not_accept_updates(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("beta_garden"), {"state": "visitors"})
        self.assertEqual(response.status_code, 405)

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AuthenticationFlowTests(TestCase):
    def setUp(self):
        self.password = "Safe-test-password-123!"
        self.user = get_user_model().objects.create_user(
            username="student",
            email="student@example.com",
            password=self.password,
        )

    def test_landing_page_is_public(self):
        response = self.client.get(reverse("landing"))

        self.assertEqual(response.status_code, 200)

    def test_dashboard_redirects_anonymous_users_to_login(self):
        response = self.client.get(reverse("dashboard"))

        expected_url = (
            f"{reverse('login')}?next={reverse('dashboard')}"
        )
        self.assertRedirects(
            response,
            expected_url,
            fetch_redirect_response=False,
        )

    def test_valid_login_redirects_to_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.username,
                "password": self.password,
            },
        )

        self.assertRedirects(
            response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

    def test_logout_preserves_workspace_and_login_restores_it(self):
        self.client.force_login(self.user)

        profile = {
            "workspace_name": "Commerce studies",
            "target_grade": 85,
            "study_hours": "2",
            "subject_count": 1,
        }
        subjects = [
            {
                "name": "Business Informatics",
                "target_grade": "85",
                "exam_date": "2026-11-20",
                "definitions": [],
                "formulas": [],
                "database_id": None,
            }
        ]

        session = self.client.session
        session["onboarding_profile"] = profile
        session["onboarding_subjects"] = subjects
        session["onboarding_complete"] = True
        session.save()

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("landing"))

        self.user.refresh_from_db()
        stored_workspace = json.loads(self.user.workspace_data)

        self.assertEqual(
            stored_workspace["onboarding_profile"],
            profile,
        )
        self.assertEqual(
            stored_workspace["onboarding_subjects"],
            subjects,
        )
        self.assertTrue(
            stored_workspace["onboarding_complete"]
        )

        login_response = self.client.post(
            reverse("login"),
            {
                "username": self.user.username,
                "password": self.password,
            },
        )

        self.assertRedirects(
            login_response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

        restored_session = self.client.session

        self.assertEqual(
            restored_session["onboarding_profile"],
            profile,
        )
        self.assertEqual(
            restored_session["onboarding_subjects"],
            subjects,
        )
        self.assertTrue(
            restored_session["onboarding_complete"]
        )

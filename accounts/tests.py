from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from dashboard.models import StudyProfile
from learning.models import Subject


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
                "login": self.user.username,
                "password": self.password,
            },
        )

        self.assertRedirects(
            response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

    def test_logout_persists_workspace_and_login_restores_it(self):
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

        stored_profile = StudyProfile.objects.get(user=self.user)
        stored_subject = Subject.objects.get(user=self.user)

        self.assertEqual(
            stored_profile.workspace_name,
            profile["workspace_name"],
        )
        self.assertEqual(stored_profile.target_grade, 85)
        self.assertEqual(stored_profile.study_hours, 2)
        self.assertEqual(stored_profile.subject_count, 1)
        self.assertTrue(stored_profile.onboarding_complete)
        self.assertEqual(
            stored_subject.name,
            "Business Informatics",
        )
        self.assertEqual(stored_subject.target_grade, 85)
        self.assertEqual(
            stored_subject.exam_date,
            date(2026, 11, 20),
        )

        login_response = self.client.post(
            reverse("login"),
            {
                "login": self.user.username,
                "password": self.password,
            },
        )

        self.assertRedirects(
            login_response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

        restored_session = self.client.session
        restored_profile = restored_session["onboarding_profile"]
        restored_subject = restored_session["onboarding_subjects"][0]

        self.assertEqual(
            restored_profile["workspace_name"],
            profile["workspace_name"],
        )
        self.assertEqual(restored_profile["target_grade"], 85)
        self.assertEqual(restored_profile["study_hours"], 2)
        self.assertEqual(restored_profile["subject_count"], 1)
        self.assertEqual(
            restored_subject["name"],
            "Business Informatics",
        )
        self.assertEqual(restored_subject["target_grade"], 85)
        self.assertEqual(
            restored_subject["exam_date"],
            "2026-11-20",
        )
        self.assertEqual(
            restored_subject["database_id"],
            stored_subject.id,
        )
        self.assertTrue(
            restored_session["onboarding_complete"]
        )

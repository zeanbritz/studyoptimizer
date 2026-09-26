from datetime import date

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import BetaInvite
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

        EmailAddress.objects.create(
            user=self.user,
            email=self.user.email,
            primary=True,
            verified=True,
        )

    def test_landing_page_is_public(self):
        response = self.client.get(reverse("landing"))
        self.assertEqual(response.status_code, 200)

    def test_login_page_uses_custom_allauth_template(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/login.html")

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

    def test_valid_username_login_redirects_to_dashboard(self):
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

    def test_valid_email_login_redirects_to_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {
                "login": self.user.email,
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

        self.assertRedirects(
            response,
            reverse("landing"),
        )

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
        restored_subject = restored_session[
            "onboarding_subjects"
        ][0]

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


class BetaInviteSignupTests(TestCase):
    def setUp(self):
        self.invite = BetaInvite.objects.get(slot=1)
        self.password = "Another-safe-password-456!"

    def signup_data(self, username, token=None):
        return {
            "username": username,
            "email": f"{username}@example.com",
            "password1": self.password,
            "password2": self.password,
            "invite_token": (
                str(token) if token is not None else ""
            ),
        }

    def test_migration_created_exactly_50_invites(self):
        self.assertEqual(BetaInvite.objects.count(), 50)

    def test_both_signup_urls_are_closed_without_invitation(self):
        for url in (
            reverse("register"),
            reverse("account_signup"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(
                    response,
                    "account/signup_closed.html",
                )

        self.assertEqual(
            get_user_model().objects.count(),
            0,
        )

    def test_valid_invite_opens_signup_page(self):
        response = self.client.get(
            f"{reverse('register')}?invite={self.invite.token}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "account/signup.html",
        )
        self.assertContains(
            response,
            f'value="{self.invite.token}"',
        )

    def test_valid_invite_creates_user_and_is_claimed(self):
        response = self.client.post(
            reverse("register"),
            self.signup_data(
                "newstudent",
                self.invite.token,
            ),
        )

        self.assertRedirects(
            response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

        new_user = get_user_model().objects.get(
            username="newstudent"
        )
        email_address = EmailAddress.objects.get(
            user=new_user,
            email="newstudent@example.com",
        )

        self.invite.refresh_from_db()

        self.assertEqual(self.invite.claimed_by, new_user)
        self.assertIsNotNone(self.invite.claimed_at)
        self.assertTrue(email_address.primary)
        self.assertFalse(email_address.verified)

    def test_used_invite_cannot_create_another_user(self):
        self.client.post(
            reverse("register"),
            self.signup_data(
                "firststudent",
                self.invite.token,
            ),
        )
        self.client.logout()

        self.client.post(
            reverse("register"),
            self.signup_data(
                "secondstudent",
                self.invite.token,
            ),
        )

        self.assertTrue(
            get_user_model().objects.filter(
                username="firststudent"
            ).exists()
        )
        self.assertFalse(
            get_user_model().objects.filter(
                username="secondstudent"
            ).exists()
        )

        self.invite.refresh_from_db()
        self.assertEqual(
            self.invite.claimed_by.username,
            "firststudent",
        )

    def test_inactive_invite_cannot_create_user(self):
        self.invite.is_active = False
        self.invite.save(update_fields=["is_active"])

        self.client.post(
            reverse("register"),
            self.signup_data(
                "blockedstudent",
                self.invite.token,
            ),
        )

        self.assertFalse(
            get_user_model().objects.filter(
                username="blockedstudent"
            ).exists()
        )

    def test_post_without_invite_cannot_create_user(self):
        self.client.post(
            reverse("register"),
            self.signup_data("uninvitedstudent"),
        )

        self.assertFalse(
            get_user_model().objects.filter(
                username="uninvitedstudent"
            ).exists()
        )
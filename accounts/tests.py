from datetime import date
import re
from urllib.parse import urlsplit

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.forms import AdultSignupForm
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


class PublicSignupTests(TestCase):
    def setUp(self):
        self.password = "Another-safe-password-456!"

    def signup_data(self, username):
        return {
            "username": username,
            "email": f"{username}@example.com",
            "password1": self.password,
            "password2": self.password,
            "age_confirmed": "on",
        }

    def test_both_signup_urls_open_without_invitation(self):
        for url in (reverse("register"), reverse("account_signup")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "account/signup.html")
                self.assertContains(response, "Sign up for free")
                self.assertNotContains(response, 'name="invite_token"')

    def test_public_signup_sends_confirmation_and_does_not_grant_beta_access(self):
        self.assertEqual(settings.ACCOUNT_EMAIL_VERIFICATION, "mandatory")
        invite = BetaInvite.objects.get(slot=1)
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
        ):
            response = self.client.post(
                reverse("register"),
                self.signup_data("newstudent"),
            )

        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, reverse("dashboard"))
        user = get_user_model().objects.get(username="newstudent")
        address = EmailAddress.objects.get(user=user)
        invite.refresh_from_db()
        self.assertTrue(address.primary)
        self.assertFalse(address.verified)
        self.assertFalse(user.beta_lifetime_access)
        self.assertIsNone(invite.claimed_by)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(user.email, mail.outbox[0].to)

        login_response = self.client.post(
            reverse("login"),
            {"login": user.username, "password": self.password},
        )
        if login_response.status_code == 302:
            self.assertNotEqual(login_response.url, reverse("dashboard"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_standard_allauth_signup_url_also_accepts_public_signup(self):
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
        ):
            response = self.client.post(
                reverse("account_signup"),
                self.signup_data("anotherstudent"),
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            get_user_model().objects.filter(
                username="anotherstudent"
            ).exists()
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_confirmation_link_is_required_before_account_access(self):
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
        ):
            self.client.post(
                reverse("register"),
                self.signup_data("verifiedstudent"),
            )

        user = get_user_model().objects.get(username="verifiedstudent")
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        link = re.search(
            r"https?://[^\s]+/accounts/confirm-email/[^\s]+",
            mail.outbox[0].body,
        )
        self.assertIsNotNone(link)
        path = urlsplit(link.group(0)).path

        self.client.get(path)
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        response = self.client.post(path)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(EmailAddress.objects.get(user=user).verified)

        self.client.logout()
        login_response = self.client.post(
            reverse("login"),
            {"login": user.username, "password": self.password},
        )
        self.assertRedirects(
            login_response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )

    def test_old_unclaimed_invite_link_does_not_grant_lifetime_access(self):
        invite = BetaInvite.objects.get(slot=1)
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
        ):
            response = self.client.post(
                f"{reverse('register')}?invite={invite.token}",
                {
                    **self.signup_data("ordinary"),
                    "invite_token": str(invite.token),
                },
            )

        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="ordinary")
        invite.refresh_from_db()
        self.assertFalse(user.beta_lifetime_access)
        self.assertIsNone(invite.claimed_by)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ACCOUNT_RATE_LIMITS={},
)
class AdultSignupTests(TestCase):
    error_message = "You must confirm you are 18 or older to create an account."

    def signup_data(self, username):
        return {
            "username": username,
            "email": f"{username}@example.com",
            "password1": "A-long-safe-student-password-486!",
            "password2": "A-long-safe-student-password-486!",
        }

    def test_both_signup_pages_have_an_unchecked_required_confirmation(self):
        for route in ("register", "account_signup"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                form = response.context["form"]
                self.assertIsInstance(form, AdultSignupForm)
                self.assertTrue(form.fields["age_confirmed"].required)
                self.assertFalse(form["age_confirmed"].value())
                self.assertIn("required", str(form["age_confirmed"]))
                self.assertNotIn("checked", str(form["age_confirmed"]))
                self.assertContains(response, 'name="age_confirmed"')
                self.assertContains(response, "I confirm I am 18 years or older.")
                self.assertContains(response, 'id="age-confirmation-help"')
                self.assertContains(response, 'href="/terms/"')
                self.assertContains(response, 'href="/privacy/"')

    def test_missing_confirmation_is_rejected_server_side_on_both_routes(self):
        for index, route in enumerate(("register", "account_signup")):
            with self.subTest(route=route):
                username = f"missing_age_{index}"
                response = self.client.post(reverse(route), self.signup_data(username))
                self.assertEqual(response.status_code, 200)
                self.assertFormError(
                    response.context["form"], "age_confirmed", self.error_message,
                )
                self.assertContains(response, self.error_message)
                self.assertFalse(
                    get_user_model().objects.filter(username=username).exists()
                )
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_false_confirmation_is_rejected_server_side_on_both_routes(self):
        for index, route in enumerate(("register", "account_signup")):
            with self.subTest(route=route):
                username = f"false_age_{index}"
                response = self.client.post(
                    reverse(route),
                    {**self.signup_data(username), "age_confirmed": "false"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertFormError(
                    response.context["form"], "age_confirmed", self.error_message,
                )
                self.assertFalse(
                    get_user_model().objects.filter(username=username).exists()
                )
        self.assertEqual(len(mail.outbox), 0)

    def test_confirmed_adult_on_each_route_still_has_to_verify_email(self):
        for index, route in enumerate(("register", "account_signup")):
            with self.subTest(route=route):
                username = f"confirmed_adult_{index}"
                response = self.client.post(
                    reverse(route),
                    {**self.signup_data(username), "age_confirmed": "on"},
                )
                self.assertRedirects(
                    response,
                    reverse("account_email_verification_sent"),
                    fetch_redirect_response=False,
                )
                user = get_user_model().objects.get(username=username)
                address = EmailAddress.objects.get(user=user)
                self.assertTrue(address.primary)
                self.assertFalse(address.verified)
                self.assertFalse(user.beta_lifetime_access)
                self.assertNotIn("_auth_user_id", self.client.session)
                self.assertIn(user.email, mail.outbox[-1].to)
        self.assertEqual(len(mail.outbox), 2)

    def test_confirmation_stays_checked_after_an_unrelated_validation_error(self):
        response = self.client.post(
            reverse("register"),
            {
                **self.signup_data("invalid_adult"),
                "age_confirmed": "on",
                "password2": "A-different-password-578!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"]["age_confirmed"].value())
        self.assertNotIn("age_confirmed", response.context["form"].errors)
        self.assertFalse(
            get_user_model().objects.filter(username="invalid_adult").exists()
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_terms_and_privacy_explain_adult_only_access(self):
        terms = self.client.get(reverse("terms_of_use"))
        privacy = self.client.get(reverse("privacy_policy"))
        self.assertContains(terms, "You must be at least 18 years old")
        self.assertContains(privacy, "StudiGarden is for people aged 18 or older")
        self.assertContains(
            privacy, "signup does not request a date of birth or an identity document",
        )
        # Other operator/privacy details still need approval before paid launch.
        self.assertContains(terms, "Draft for review before launch")
        self.assertContains(privacy, "Draft for review before launch")

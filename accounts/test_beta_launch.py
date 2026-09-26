from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import BetaInvite


class BetaInviteAdminTests(TestCase):
    def test_superuser_can_see_invitation_links(self):
        superuser = get_user_model().objects.create_superuser(
            username="owner",
            email="owner@example.com",
            password="Safe-test-password-123!",
        )
        self.client.force_login(superuser)

        invite = BetaInvite.objects.get(slot=1)
        response = self.client.get(
            reverse("admin:accounts_betainvite_changelist")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f"invite={invite.token}",
        )

    def test_staff_user_cannot_see_invitation_links(self):
        staff_user = get_user_model().objects.create_user(
            username="staff",
            email="staff@example.com",
            password="Safe-test-password-123!",
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(
            reverse("admin:accounts_betainvite_changelist")
        )

        self.assertEqual(response.status_code, 403)


@override_settings(
    ACCOUNT_EMAIL_VERIFICATION="mandatory",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class BetaInviteEmailVerificationTests(TestCase):
    def test_invited_student_must_verify_email_before_login(self):
        invite = BetaInvite.objects.get(slot=1)

        response = self.client.post(
            reverse("register"),
            {
                "username": "newstudent",
                "email": "newstudent@example.com",
                "password1": "Another-safe-password-456!",
                "password2": "Another-safe-password-456!",
                "invite_token": str(invite.token),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(
            response["Location"],
            reverse("dashboard"),
        )

        student = get_user_model().objects.get(
            username="newstudent"
        )
        email_address = EmailAddress.objects.get(user=student)

        invite.refresh_from_db()

        self.assertFalse(email_address.verified)
        self.assertEqual(invite.claimed_by, student)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(
            any(
                "newstudent@example.com" in message.to
                for message in mail.outbox
            )
        )

    def test_existing_verified_student_can_still_login(self):
        student = get_user_model().objects.create_user(
            username="existingstudent",
            email="existing@example.com",
            password="Safe-test-password-123!",
        )
        EmailAddress.objects.create(
            user=student,
            email=student.email,
            primary=True,
            verified=True,
        )

        response = self.client.post(
            reverse("login"),
            {
                "login": student.username,
                "password": "Safe-test-password-123!",
            },
        )

        self.assertRedirects(
            response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )
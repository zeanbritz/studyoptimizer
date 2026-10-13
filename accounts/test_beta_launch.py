from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import BetaInvite


class LegacyBetaInviteAdminTests(TestCase):
    def test_superuser_can_view_existing_claims_but_not_issue_invites(self):
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
        self.assertContains(response, "Unused (legacy)")
        self.assertNotContains(response, f"invite={invite.token}")
        self.assertNotContains(response, "Open / copy invitation")

    def test_staff_user_cannot_view_existing_claims(self):
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


class ExistingVerifiedAccountTests(TestCase):
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

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch

from .models import SupportQuery


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    STUDIGARDEN_SUPPORT_EMAIL="zd.britz@icloud.com",
)
class SupportQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="support-student",
            email="student@example.com",
            password="Safe-test-password-123!",
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("submit_support_query")

    def test_profile_shows_support_widget(self):
        response = self.client.get(reverse("my_plan"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="profile-support-launcher"')
        self.assertContains(response, "Contact support")

    def test_request_is_logged_and_emailed(self):
        response = self.client.post(
            self.url,
            {
                "category": "payments",
                "message": "  My refund is still pending.  ",
                "page_path": "/my-plan/?private=value",
                "status": "resolved",
                "email_status": "sent",
            },
        )

        self.assertEqual(response.status_code, 200)
        query = SupportQuery.objects.get()
        self.assertEqual(query.user, self.user)
        self.assertEqual(query.username, "support-student")
        self.assertEqual(query.email, "student@example.com")
        self.assertEqual(query.category, SupportQuery.Category.PAYMENTS)
        self.assertEqual(query.message, "My refund is still pending.")
        self.assertEqual(query.page_path, "/my-plan/")
        self.assertEqual(query.status, SupportQuery.Status.NEW)
        self.assertEqual(query.email_status, SupportQuery.EmailStatus.SENT)
        self.assertIsNotNone(query.email_attempted_at)

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["zd.britz@icloud.com"])
        self.assertEqual(message.reply_to, ["student@example.com"])
        self.assertIn(f"support #{query.pk}", message.subject)
        self.assertIn("My refund is still pending.", message.body)
        self.assertIn("student@example.com", message.body)
        self.assertEqual(response.json()["ok"], True)
        self.assertIn(f"#{query.pk}", response.json()["message"])

    def test_email_failure_keeps_admin_record(self):
        with patch("accounts.support_views.EmailMessage.send", side_effect=RuntimeError):
            response = self.client.post(
                self.url,
                {"category": "technical", "message": "The page will not load."},
            )

        self.assertEqual(response.status_code, 202)
        query = SupportQuery.objects.get()
        self.assertEqual(query.email_status, SupportQuery.EmailStatus.FAILED)
        self.assertEqual(query.status, SupportQuery.Status.NEW)
        self.assertTrue(response.json()["ok"])
        self.assertIn("admin log", response.json()["message"])

    def test_invalid_request_is_rejected(self):
        for data in (
            {"category": "invalid", "message": "Help"},
            {"category": "account", "message": "   "},
            {"category": "other", "message": "x" * 4001},
        ):
            with self.subTest(data=data):
                response = self.client.post(self.url, data)
                self.assertEqual(response.status_code, 400)

        self.assertFalse(SupportQuery.objects.exists())

    def test_anonymous_and_csrf_requests_are_blocked(self):
        self.client.logout()
        response = self.client.post(
            self.url, {"category": "account", "message": "Help"},
        )
        self.assertEqual(response.status_code, 302)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(
            self.url, {"category": "account", "message": "Help"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SupportQuery.objects.exists())

    def test_rate_limit_is_five_requests_per_hour(self):
        for _ in range(5):
            SupportQuery.objects.create(
                user=self.user,
                username=self.user.username,
                email=self.user.email,
                category=SupportQuery.Category.OTHER,
                message="Earlier request",
            )

        response = self.client.post(
            self.url, {"category": "other", "message": "One more"},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(SupportQuery.objects.count(), 5)

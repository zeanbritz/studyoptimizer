from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import BetaInvite, StudyMembership


class MyPlanPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="plan-student",
            password="safe-test-password",
        )
        self.url = reverse("my_plan")

    def test_anonymous_visitor_is_sent_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/login/"))

    def test_user_without_plan_sees_no_paid_plan(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No paid plan")
        self.assertContains(response, "Paid subscriptions are not open yet")

    def test_beta_user_sees_free_access(self):
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invited beta access")
        self.assertContains(response, "permanent free access")

    def test_claimed_invite_sees_beta_access_even_without_flag(self):
        invite = BetaInvite.objects.get(slot=1)
        invite.claimed_by = self.user
        invite.save(update_fields=["claimed_by"])
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invited beta access")

    def test_monthly_member_sees_plan_and_status(self):
        StudyMembership.objects.create(
            user=self.user,
            plan=StudyMembership.Plan.MONTHLY,
            status=StudyMembership.Status.ACTIVE,
            paid_until=timezone.now() + timedelta(days=30),
        )
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monthly plan")
        self.assertContains(response, "R99 per month")
        self.assertContains(response, "Active")
        self.assertContains(response, "Paid access until")

    def test_yearly_member_sees_one_time_plan(self):
        StudyMembership.objects.create(
            user=self.user,
            plan=StudyMembership.Plan.YEARLY,
            status=StudyMembership.Status.ACTIVE,
            paid_until=timezone.now() + timedelta(days=365),
        )
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Yearly plan")
        self.assertContains(response, "R999 for 12 months")
        self.assertContains(response, "does not renew automatically")
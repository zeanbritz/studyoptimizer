from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import BetaInvite, StudyMembership, StudyTier


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

    def test_user_without_paid_plan_sees_free_account(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Free account")
        self.assertContains(response, "No payment details are needed")

    def test_beta_user_sees_free_access(self):
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invited beta access")
        self.assertContains(response, "permanent free access")
        self.assertContains(response, "Bloom without a monthly payment")

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
            tier=StudyTier.GROW,
            plan=StudyMembership.Plan.MONTHLY,
            status=StudyMembership.Status.ACTIVE,
            paid_until=timezone.now() + timedelta(days=30),
        )
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Grow plan")
        self.assertContains(response, "R35 per month")
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
        self.assertContains(response, "Bloom plan")
        self.assertContains(response, "Prepaid access for 12 months")
        self.assertContains(response, "does not renew automatically")

    def test_expired_member_sees_free_plan_without_losing_data_message(self):
        StudyMembership.objects.create(
            user=self.user,
            plan=StudyMembership.Plan.YEARLY,
            status=StudyMembership.Status.EXPIRED,
            paid_until=timezone.now() - timedelta(days=1),
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertContains(response, "Free account")
        self.assertContains(response, "saved subjects and learning items remain available")

    def test_bloom_member_sees_bloom_monthly_price(self):
        StudyMembership.objects.create(
            user=self.user,
            tier=StudyTier.BLOOM,
            plan=StudyMembership.Plan.MONTHLY,
            status=StudyMembership.Status.ACTIVE,
            paid_until=timezone.now() + timedelta(days=30),
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertContains(response, "Bloom plan")
        self.assertContains(response, "R90 per month")
        self.assertNotContains(response, "R35 per month")

    def test_pending_membership_keeps_free_account_until_payment_is_confirmed(self):
        StudyMembership.objects.create(
            user=self.user, tier=StudyTier.GROW, plan=StudyMembership.Plan.MONTHLY,
            paid_until=timezone.now() + timedelta(days=30),
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertContains(response, "Free account")
        self.assertContains(response, "Grow plan is awaiting confirmed payment")

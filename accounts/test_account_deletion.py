from datetime import date, timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from dashboard.models import BetaFeedback, DailyReviewPlan, StudyAvailability, StudyProfile
from learning.models import Subject

from .models import (
    StudyMembership,
    StudyMonthlyUsage,
    StudyPayment,
    StudyRefund,
    SupportQuery,
)


class AccountDeletionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="delete-student",
            email="delete-student@example.com",
            password="Safe-test-password-123!",
            first_name="Delete",
            last_name="Student",
        )
        EmailAddress.objects.create(
            user=self.user,
            email=self.user.email,
            primary=True,
            verified=True,
        )
        self.client.force_login(self.user)
        self.url = reverse("delete_account")

    def _study_data(self):
        Subject.objects.create(user=self.user, name="Biology")
        StudyProfile.objects.create(user=self.user, workspace_name="My studies")
        StudyAvailability.objects.create(user=self.user)
        DailyReviewPlan.objects.create(
            user=self.user,
            day=date.today(),
            settings_signature="signature",
        )
        BetaFeedback.objects.create(
            user=self.user,
            category=BetaFeedback.Category.BUG,
            message="Earlier feedback",
        )
        StudyMonthlyUsage.objects.create(
            user=self.user,
            period_start=date.today().replace(day=1),
            pdf_exports=1,
            summary_pages=2,
        )

    def _payment(self, status=StudyPayment.Status.PENDING):
        return StudyPayment.objects.create(
            user=self.user,
            tier="grow",
            plan="monthly",
            mode="live",
            source="checkout",
            expected_amount_cents=3500,
            status=status,
            checkout_email=self.user.email,
            authorization_url="https://checkout.paystack.com/safeTest",
        )

    def test_free_user_can_delete_study_data_and_login(self):
        self._study_data()
        payment = self._payment()
        support = SupportQuery.objects.create(
            user=self.user,
            username=self.user.username,
            email=self.user.email,
            category=SupportQuery.Category.ACCOUNT,
            message="Earlier support request",
        )
        original_pk = self.user.pk

        response = self.client.post(self.url, {"confirm_delete": "yes"})

        self.assertRedirects(response, reverse("landing"))
        deleted = get_user_model().objects.get(pk=original_pk)
        self.assertFalse(deleted.is_active)
        self.assertIsNotNone(deleted.deleted_at)
        self.assertTrue(deleted.username.startswith(f"deleted-{original_pk}-"))
        self.assertEqual(deleted.email, "")
        self.assertEqual(deleted.first_name, "")
        self.assertEqual(deleted.last_name, "")
        self.assertFalse(deleted.has_usable_password())
        self.assertFalse(EmailAddress.objects.filter(user_id=original_pk).exists())
        self.assertFalse(Subject.objects.filter(user_id=original_pk).exists())
        self.assertFalse(StudyProfile.objects.filter(user_id=original_pk).exists())
        self.assertFalse(StudyAvailability.objects.filter(user_id=original_pk).exists())
        self.assertFalse(DailyReviewPlan.objects.filter(user_id=original_pk).exists())
        self.assertFalse(BetaFeedback.objects.filter(user_id=original_pk).exists())
        self.assertFalse(StudyMonthlyUsage.objects.filter(user_id=original_pk).exists())

        payment.refresh_from_db()
        self.assertEqual(payment.user_id, original_pk)
        self.assertIsNotNone(payment.discarded_at)
        self.assertEqual(payment.authorization_url, "")
        support.refresh_from_db()
        self.assertIsNone(support.user_id)
        self.assertEqual(support.email, "delete-student@example.com")

        self.assertRedirects(
            self.client.get(reverse("my_plan")),
            f"{reverse('login')}?next={reverse('my_plan')}",
        )

    def test_active_monthly_subscription_must_be_cancelled_first(self):
        subject = Subject.objects.create(user=self.user, name="Physics")
        StudyMembership.objects.create(
            user=self.user,
            tier="grow",
            plan="monthly",
            payment_mode="live",
            status="active",
            paid_until=timezone.now() + timedelta(days=20),
            paystack_subscription_code="SUB_owned",
        )

        profile = self.client.get(reverse("my_plan"))
        self.assertContains(profile, "Cancel your monthly subscription")
        self.assertNotContains(profile, 'id="delete-account-open"')

        response = self.client.post(self.url, {"confirm_delete": "yes"})
        self.assertRedirects(response, reverse("my_plan"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(Subject.objects.filter(pk=subject.pk).exists())

    def test_non_renewing_paid_account_can_be_deleted(self):
        StudyMembership.objects.create(
            user=self.user,
            tier="grow",
            plan="monthly",
            payment_mode="live",
            status="non_renewing",
            paid_until=timezone.now() + timedelta(days=20),
            paystack_subscription_code="SUB_stopped",
        )

        profile = self.client.get(reverse("my_plan"))
        self.assertContains(profile, 'id="delete-account-open"')
        response = self.client.post(self.url, {"confirm_delete": "yes"})

        self.assertRedirects(response, reverse("landing"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(StudyMembership.objects.filter(user_id=self.user.pk).exists())

    def test_open_refund_blocks_deletion(self):
        payment = self._payment(status=StudyPayment.Status.SUCCEEDED)
        StudyRefund.objects.create(
            user=self.user,
            payment=payment,
            reason=StudyRefund.Reason.FIRST_PAYMENT,
            mode="live",
            status=StudyRefund.Status.PROCESSING,
            amount_cents=3500,
        )

        response = self.client.post(self.url, {"confirm_delete": "yes"})

        self.assertRedirects(response, reverse("my_plan"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_confirmation_post_csrf_and_authentication_are_required(self):
        response = self.client.post(self.url, {})
        self.assertRedirects(response, reverse("my_plan"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

        self.assertEqual(self.client.get(self.url).status_code, 405)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(self.url, {"confirm_delete": "yes"})
        self.assertEqual(response.status_code, 403)

        self.client.logout()
        response = self.client.post(self.url, {"confirm_delete": "yes"})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_profile_uses_sidebar_and_confirmation_dialog(self):
        response = self.client.get(reverse("my_plan"))

        self.assertContains(response, 'class="profile-layout"')
        self.assertContains(response, 'id="delete-account-dialog"')
        self.assertContains(response, 'name="confirm_delete" value="yes" required')
        self.assertContains(response, "all study content you created will be permanently deleted")

    def test_administrator_cannot_delete_account_here(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=("is_staff", "is_superuser"))

        response = self.client.post(self.url, {"confirm_delete": "yes"})

        self.assertRedirects(response, reverse("my_plan"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

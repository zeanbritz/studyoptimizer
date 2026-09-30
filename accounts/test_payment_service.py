from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import StudyMembership, StudyPayment
from .payment_service import (
    CheckoutNotAllowed,
    create_test_checkout_attempt,
)


class TestCheckoutAttemptTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="checkout-student",
            email="student@example.com",
            password="safe-test-password",
        )
        self.email_address = EmailAddress.objects.create(
            user=self.user,
            email=self.user.email,
            verified=True,
            primary=True,
        )

    def test_monthly_amount_is_set_by_server(self):
        payment = create_test_checkout_attempt(
            user=self.user,
            plan=StudyMembership.Plan.MONTHLY,
        )

        self.assertEqual(payment.expected_amount_cents, 9900)
        self.assertEqual(payment.currency, "ZAR")
        self.assertEqual(payment.mode, StudyPayment.Mode.TEST)
        self.assertEqual(payment.status, StudyPayment.Status.CREATED)

    def test_yearly_amount_is_set_by_server(self):
        payment = create_test_checkout_attempt(
            user=self.user,
            plan=StudyMembership.Plan.YEARLY,
        )

        self.assertEqual(payment.expected_amount_cents, 99900)
        self.assertEqual(payment.mode, StudyPayment.Mode.TEST)

    def test_unknown_plan_is_rejected(self):
        with self.assertRaises(CheckoutNotAllowed):
            create_test_checkout_attempt(user=self.user, plan="free")

        self.assertEqual(StudyPayment.objects.count(), 0)

    def test_beta_user_cannot_start_checkout(self):
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])

        with self.assertRaises(CheckoutNotAllowed):
            create_test_checkout_attempt(
                user=self.user,
                plan=StudyMembership.Plan.MONTHLY,
            )

        self.assertEqual(StudyPayment.objects.count(), 0)

    def test_unverified_email_cannot_start_checkout(self):
        self.email_address.verified = False
        self.email_address.save(update_fields=["verified"])

        with self.assertRaises(CheckoutNotAllowed):
            create_test_checkout_attempt(
                user=self.user,
                plan=StudyMembership.Plan.MONTHLY,
            )

        self.assertEqual(StudyPayment.objects.count(), 0)

    def test_inactive_user_cannot_start_checkout(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        with self.assertRaises(CheckoutNotAllowed):
            create_test_checkout_attempt(
                user=self.user,
                plan=StudyMembership.Plan.MONTHLY,
            )

        self.assertEqual(StudyPayment.objects.count(), 0)
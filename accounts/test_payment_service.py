from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings

from .access import get_study_tier
from .models import BetaInvite, StudyMembership, StudyPayment, StudyTier
from .payment_service import (
    CheckoutNotAllowed,
    create_test_checkout_attempt,
)


@override_settings(PAYSTACK_TEST_PLAN_CODES={
    "grow": "PLN_glgi3r3klhjabz6",
    "bloom": "PLN_zo1y9g6fw3mbxje",
})
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

    def test_grow_price_and_plan_code_are_set_by_server(self):
        payment = create_test_checkout_attempt(
            user=self.user,
            tier=StudyTier.GROW,
            plan=StudyMembership.Plan.MONTHLY,
        )

        self.assertEqual(payment.tier, StudyTier.GROW)
        self.assertEqual(payment.expected_amount_cents, 3500)
        self.assertEqual(payment.paystack_plan_code, "PLN_glgi3r3klhjabz6")
        self.assertEqual(payment.currency, "ZAR")
        self.assertEqual(payment.mode, StudyPayment.Mode.TEST)
        self.assertEqual(payment.status, StudyPayment.Status.CREATED)
        self.assertFalse(StudyMembership.objects.filter(user=self.user).exists())
        self.assertEqual(get_study_tier(self.user), StudyTier.FREE)

    def test_bloom_price_and_plan_code_are_set_by_server(self):
        payment = create_test_checkout_attempt(
            user=self.user,
            tier=StudyTier.BLOOM,
        )

        self.assertEqual(payment.tier, StudyTier.BLOOM)
        self.assertEqual(payment.plan, StudyMembership.Plan.MONTHLY)
        self.assertEqual(payment.expected_amount_cents, 9000)
        self.assertEqual(payment.paystack_plan_code, "PLN_zo1y9g6fw3mbxje")
        self.assertEqual(payment.mode, StudyPayment.Mode.TEST)

    def test_free_and_unknown_tiers_cannot_create_payments(self):
        for tier in (StudyTier.FREE, "gold", "monthly", "", None, [], {}):
            with self.subTest(tier=tier), self.assertRaises(CheckoutNotAllowed):
                create_test_checkout_attempt(user=self.user, tier=tier)

        self.assertEqual(StudyPayment.objects.count(), 0)

    def test_yearly_and_unknown_billing_periods_cannot_start_new_checkout(self):
        for plan in (StudyMembership.Plan.YEARLY, "free", "weekly", None):
            with self.subTest(plan=plan), self.assertRaises(CheckoutNotAllowed):
                create_test_checkout_attempt(user=self.user, tier=StudyTier.GROW, plan=plan)

        self.assertEqual(StudyPayment.objects.count(), 0)

    def test_beta_user_cannot_start_checkout(self):
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])

        with self.assertRaises(CheckoutNotAllowed):
            create_test_checkout_attempt(
                user=self.user,
                tier=StudyTier.GROW,
                plan=StudyMembership.Plan.MONTHLY,
            )

        self.assertEqual(StudyPayment.objects.count(), 0)

    def test_unverified_email_cannot_start_checkout(self):
        self.email_address.verified = False
        self.email_address.save(update_fields=["verified"])

        with self.assertRaises(CheckoutNotAllowed):
            create_test_checkout_attempt(
                user=self.user,
                tier=StudyTier.GROW,
                plan=StudyMembership.Plan.MONTHLY,
            )

        self.assertEqual(StudyPayment.objects.count(), 0)

    def test_inactive_user_cannot_start_checkout(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        with self.assertRaises(CheckoutNotAllowed):
            create_test_checkout_attempt(
                user=self.user,
                tier=StudyTier.GROW,
                plan=StudyMembership.Plan.MONTHLY,
            )

        self.assertEqual(StudyPayment.objects.count(), 0)

    def test_claimed_invitee_cannot_start_checkout_without_beta_flag(self):
        invite = BetaInvite.objects.get(slot=1)
        invite.claimed_by = self.user
        invite.save(update_fields=["claimed_by"])
        with self.assertRaises(CheckoutNotAllowed):
            create_test_checkout_attempt(user=self.user, tier=StudyTier.BLOOM)
        self.assertFalse(StudyPayment.objects.exists())

    def test_anonymous_accounts_cannot_start_checkout(self):
        for user in (None, AnonymousUser()):
            with self.subTest(user=user), self.assertRaises(CheckoutNotAllowed):
                create_test_checkout_attempt(user=user, tier=StudyTier.GROW)
        self.assertFalse(StudyPayment.objects.exists())

    def test_missing_plan_code_is_rejected_before_a_payment_is_saved(self):
        with self.settings(PAYSTACK_TEST_PLAN_CODES={"grow": ""}):
            with self.assertRaises(CheckoutNotAllowed):
                create_test_checkout_attempt(user=self.user, tier=StudyTier.GROW)
        self.assertFalse(StudyPayment.objects.exists())

    def test_saved_attempt_keeps_original_price_and_plan_code(self):
        payment = create_test_checkout_attempt(user=self.user, tier=StudyTier.GROW)
        with self.settings(PAYSTACK_TEST_PLAN_CODES={"grow": "PLN_replacement"}):
            replacement = create_test_checkout_attempt(user=self.user, tier=StudyTier.GROW)
        payment.refresh_from_db()
        self.assertEqual(payment.paystack_plan_code, "PLN_glgi3r3klhjabz6")
        self.assertEqual(payment.expected_amount_cents, 3500)
        self.assertEqual(replacement.paystack_plan_code, "PLN_replacement")

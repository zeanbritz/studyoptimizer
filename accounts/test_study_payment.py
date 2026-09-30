import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import StudyMembership, StudyPayment


class StudyPaymentModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="payment-student",
            password="safe-test-password",
        )

    def make_payment(self, **overrides):
        values = {
            "user": self.user,
            "plan": StudyMembership.Plan.MONTHLY,
            "mode": StudyPayment.Mode.TEST,
            "expected_amount_cents": 9900,
        }
        values.update(overrides)
        return StudyPayment.objects.create(**values)

    def test_reference_is_generated_and_paystack_compatible(self):
        first = self.make_payment()
        second = self.make_payment()

        self.assertNotEqual(first.reference, second.reference)
        self.assertLessEqual(len(first.reference), 40)
        self.assertIsNotNone(
            re.fullmatch(r"[A-Za-z0-9.=\-]+", first.reference)
        )
        self.assertEqual(first.currency, "ZAR")
        self.assertEqual(first.status, StudyPayment.Status.CREATED)
        self.assertEqual(first.source, StudyPayment.Source.CHECKOUT)

    def test_reference_cannot_be_reused(self):
        first = self.make_payment()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_payment(reference=first.reference)

    def test_expected_amount_must_be_positive(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_payment(expected_amount_cents=0)

    def test_transaction_id_cannot_repeat_in_same_mode(self):
        self.make_payment(paystack_transaction_id=123456)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_payment(paystack_transaction_id=123456)

    def test_transaction_id_can_exist_in_separate_modes(self):
        self.make_payment(
            mode=StudyPayment.Mode.TEST,
            paystack_transaction_id=123456,
        )
        live_payment = self.make_payment(
            mode=StudyPayment.Mode.LIVE,
            paystack_transaction_id=123456,
        )

        self.assertEqual(live_payment.mode, StudyPayment.Mode.LIVE)

    def test_yearly_payment_keeps_its_original_price(self):
        payment = self.make_payment(
            plan=StudyMembership.Plan.YEARLY,
            expected_amount_cents=99900,
        )

        self.assertEqual(payment.plan, StudyMembership.Plan.YEARLY)
        self.assertEqual(payment.expected_amount_cents, 99900)
"""Plan-switch policy and durable records; all network access is forbidden."""

from datetime import timedelta
from unittest.mock import Mock, patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from .access import get_study_tier
from .admin import StudyPlanChangeAdmin
from .models import StudyMembership, StudyPayment, StudyPlanChange, StudyRefund
from .payment_service import CheckoutNotAllowed
from .paystack_client import PaystackLiveClient
from .plan_changes import OPEN_CHANGE_STATES, plan_changes_enabled, quote_plan_change
from .test_live_payments import LIVE


CHANGE_SETTINGS = {
    **LIVE, "PAYSTACK_LIVE_PLAN_CHANGES_ENABLED": True, "PAYSTACK_LIVE_REFUNDS_ENABLED": True,
}


@override_settings(**CHANGE_SETTINGS)
class PlanChangePolicyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="switch-policy", email="switch@example.com")
        EmailAddress.objects.create(user=self.user, email=self.user.email, verified=True, primary=True)
        self.end = timezone.now() + timedelta(days=19, hours=3)
        self.member = StudyMembership.objects.create(
            user=self.user, tier="grow", plan="monthly", payment_mode="live", status="active",
            paid_until=self.end, paystack_customer_code="CUS_owner", paystack_subscription_code="SUB_old",
        )
        self.network = patch("accounts.paystack_client.build_opener", side_effect=AssertionError("No real billing permitted")).start()
        self.addCleanup(patch.stopall)

    def quote(self, tier):
        return quote_plan_change(user=self.user, tier=tier)

    def change_member(self, **values):
        StudyMembership.objects.filter(pk=self.member.pk).update(**values)
        self.member.refresh_from_db()

    def test_upgrade_charges_full_new_month_and_requests_current_lower_payment_refund(self):
        quote = self.quote("bloom")
        self.assertEqual((quote.kind, quote.amount_due_now_cents, quote.next_monthly_amount_cents), ("upgrade", 9000, 9000))
        self.assertTrue(quote.refund_current_lower_payment)
        self.assertLess(quote.effective_at, self.end)
        self.assertEqual(get_study_tier(self.user), "grow")
        self.assertFalse(StudyPlanChange.objects.exists())
        self.assertFalse(StudyPayment.objects.exists())
        self.assertFalse(StudyRefund.objects.exists())
        self.network.assert_not_called()

    def test_bloom_to_grow_is_zero_now_and_35_from_paid_through_date(self):
        self.change_member(tier="bloom")
        quote = self.quote("grow")
        self.assertEqual((quote.kind, quote.amount_due_now_cents, quote.next_monthly_amount_cents), ("downgrade", 0, 3500))
        self.assertEqual(quote.effective_at, self.end)
        self.assertFalse(quote.refund_current_lower_payment)
        self.assertEqual(get_study_tier(self.user), "bloom")

    def test_free_downgrade_keeps_paid_time_without_a_new_charge(self):
        for tier in ("grow", "bloom"):
            with self.subTest(tier=tier):
                self.change_member(tier=tier)
                quote = self.quote("free")
                self.assertEqual((quote.kind, quote.to_tier, quote.amount_due_now_cents, quote.next_monthly_amount_cents), ("downgrade", "free", 0, 0))
                self.assertEqual(quote.effective_at, self.end)
                self.assertEqual(get_study_tier(self.user), tier)

    def test_quotes_use_billing_period_not_first_day_of_calendar_month(self):
        quote = self.quote("free")
        self.assertEqual(quote.effective_at, self.member.paid_until)
        self.assertEqual(quote.effective_at.hour, self.end.hour)

    def test_cancelled_grow_can_resume_without_charging_for_the_same_time_twice(self):
        self.change_member(status="non_renewing")
        quote = self.quote("grow")
        self.assertEqual((quote.kind, quote.amount_due_now_cents, quote.next_monthly_amount_cents), ("resume", 0, 3500))
        self.assertEqual(quote.effective_at, self.end)

    def test_active_same_plan_is_not_a_new_purchase(self):
        with self.assertRaises(CheckoutNotAllowed):
            self.quote("grow")

    def test_non_renewing_grow_can_upgrade_using_same_refund_policy(self):
        self.change_member(status="non_renewing")
        quote = self.quote("bloom")
        self.assertTrue(quote.refund_current_lower_payment)
        self.assertEqual(quote.amount_due_now_cents, 9000)

    def test_expired_membership_restarts_without_refunding_a_past_period(self):
        self.change_member(status="expired", paid_until=timezone.now() - timedelta(seconds=1))
        quote = self.quote("bloom")
        self.assertEqual((quote.kind, quote.amount_due_now_cents), ("restart", 9000))
        self.assertFalse(quote.refund_current_lower_payment)

    def test_unfunded_grace_is_not_mistaken_for_a_paid_month(self):
        self.change_member(tier="bloom", status="past_due", paid_until=timezone.now() - timedelta(days=1), grace_until=timezone.now() + timedelta(days=1))
        self.assertEqual(get_study_tier(self.user), "bloom")
        quote = self.quote("grow")
        self.assertEqual((quote.kind, quote.amount_due_now_cents), ("restart", 3500))
        self.assertFalse(quote.refund_current_lower_payment)

    def test_no_free_downgrade_debit_when_previous_period_has_ended(self):
        self.change_member(status="expired", paid_until=timezone.now() - timedelta(days=1))
        quote = self.quote("free")
        self.assertEqual((quote.kind, quote.next_monthly_amount_cents), ("downgrade", 0))
        self.assertGreater(quote.effective_at, self.member.paid_until)

    def test_paused_sales_still_allow_free_cancellation_not_new_paid_billing(self):
        with override_settings(PAYSTACK_LIVE_CHECKOUT_ENABLED=False):
            self.assertEqual(self.quote("free").next_monthly_amount_cents, 0)
            with self.assertRaises(CheckoutNotAllowed):
                self.quote("bloom")

    def test_upgrade_cannot_charge_while_automatic_refunds_are_paused(self):
        with override_settings(PAYSTACK_LIVE_REFUNDS_ENABLED=False):
            with self.assertRaises(CheckoutNotAllowed):
                self.quote("bloom")
            self.change_member(tier="bloom")
            self.assertEqual(self.quote("grow").kind, "downgrade")

    def test_switching_flag_and_live_gate_fail_closed(self):
        for setting, value in (("PAYSTACK_LIVE_PLAN_CHANGES_ENABLED", False), ("PAYSTACK_LIVE_ENABLED", False), ("DEBUG", True)):
            with self.subTest(setting=setting), override_settings(**{setting: value}):
                self.assertFalse(plan_changes_enabled())
                with self.assertRaises(CheckoutNotAllowed):
                    self.quote("bloom")

    def test_invalid_unknown_and_non_string_tiers_are_rejected(self):
        for tier in (None, [], {}, "yearly", "BLOOM", "enterprise"):
            with self.subTest(tier=tier), self.assertRaises(CheckoutNotAllowed):
                self.quote(tier)

    def test_no_plan_change_for_test_or_yearly_or_unverified_current_membership(self):
        for values in ({"payment_mode": "test"}, {"plan": "yearly"}, {"status": "pending"}, {"paid_until": None}, {"paystack_customer_code": "bad"}):
            with self.subTest(values=values):
                with transaction.atomic():
                    self.change_member(**values)
                    with self.assertRaises(CheckoutNotAllowed):
                        self.quote("bloom")
                    transaction.set_rollback(True)

    def test_permanent_free_and_inactive_accounts_cannot_start_paid_switches(self):
        for field in ("beta_lifetime_access", "is_superuser", "is_active"):
            original = getattr(self.user, field)
            setattr(self.user, field, field != "is_active")
            with self.subTest(field=field), self.assertRaises(CheckoutNotAllowed):
                self.quote("bloom")
            setattr(self.user, field, original)

    def test_verified_email_required_for_new_paid_authorisation_not_cancelling(self):
        EmailAddress.objects.filter(user=self.user).update(verified=False)
        with self.assertRaises(CheckoutNotAllowed):
            self.quote("bloom")
        self.assertEqual(self.quote("free").to_tier, "free")


class PlanChangeRecordTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="change-records", email="records@example.com")
        self.payment = StudyPayment.objects.create(user=self.user, tier="grow", plan="monthly", mode="live", status="succeeded", expected_amount_cents=3500)
        self.end = timezone.now() + timedelta(days=10)

    def change(self, **values):
        return StudyPlanChange.objects.create(**{
            "user": self.user, "kind": "upgrade", "from_tier": "grow", "to_tier": "bloom",
            "state": "queued", "from_subscription_code": "SUB_old", "from_plan_code": "PLN_grow",
            "to_plan_code": "PLN_bloom", "amount_due_now_cents": 9000, "monthly_amount_cents": 9000,
            "customer_code": "CUS_owner", "billing_email": self.user.email,
            "from_paid_until": self.end, "effective_at": timezone.now(), "previous_payment": self.payment,
            **values,
        })

    def test_only_one_unfinished_change_per_user_including_attention_cases(self):
        first = self.change()
        for state in OPEN_CHANGE_STATES:
            StudyPlanChange.objects.filter(pk=first.pk).update(state=state)
            with self.subTest(state=state), self.assertRaises(IntegrityError), transaction.atomic():
                self.change()

    def test_completed_history_does_not_prevent_a_later_change(self):
        first = self.change(state="applied")
        second = self.change(state="cancelled")
        third = self.change()
        self.assertEqual(StudyPlanChange.objects.filter(user=self.user).count(), 3)
        self.assertNotEqual(first.pk, third.pk)
        self.assertNotEqual(second.pk, third.pk)

    def test_direction_price_currency_and_no_downgrade_charge_are_database_constraints(self):
        for values in (
            {"from_tier": "bloom", "to_tier": "grow"},
            {"kind": "resume"},
            {"kind": "downgrade", "from_tier": "bloom", "to_tier": "grow"},
            {"currency": "USD"}, {"monthly_amount_cents": 0}, {"to_plan_code": ""},
            {"amount_due_now_cents": 3500},
        ):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                self.change(**values)

    def test_a_saved_scheduled_change_does_not_grant_or_remove_access(self):
        StudyMembership.objects.create(user=self.user, tier="bloom", plan="monthly", status="active", paid_until=self.end)
        self.change(kind="downgrade", from_tier="bloom", to_tier="grow", state="scheduled", to_plan_code="PLN_grow", amount_due_now_cents=0, monthly_amount_cents=3500, effective_at=self.end)
        self.assertEqual(get_study_tier(self.user), "bloom")
        self.assertEqual(StudyPayment.objects.count(), 1)
        self.assertFalse(StudyRefund.objects.exists())

    def test_declined_guarantee_record_does_not_block_a_distinct_upgrade_refund(self):
        denied = StudyRefund.objects.create(user=self.user, payment=self.payment, amount_cents=3500, status="ineligible")
        upgrade = StudyRefund.objects.create(user=self.user, payment=self.payment, amount_cents=3500, reason="upgrade")
        self.assertNotEqual(denied.pk, upgrade.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudyRefund.objects.create(user=self.user, payment=self.payment, amount_cents=3500, reason="discarded_checkout")
        denied.refresh_from_db()
        self.assertEqual(denied.status, "ineligible")

    def test_guarantee_still_once_per_account_and_full_refund_once_per_payment(self):
        refund = StudyRefund.objects.create(user=self.user, payment=self.payment, amount_cents=3500)
        for status in ("requested", "submitting", "processing", "completed", "attention"):
            StudyRefund.objects.filter(pk=refund.pk).update(status=status)
            with self.subTest(status=status), self.assertRaises(IntegrityError), transaction.atomic():
                StudyRefund.objects.create(user=self.user, payment=self.payment, amount_cents=3500, reason="upgrade")
        other = StudyPayment.objects.create(user=self.user, tier="grow", plan="monthly", mode="live", expected_amount_cents=3500)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudyRefund.objects.create(user=self.user, payment=other, amount_cents=3500)

    def test_admin_cannot_add_change_or_delete_saved_billing_intent(self):
        administrator = get_user_model().objects.create_superuser(username="intent-admin", email="admin@example.com", password=None)
        admin = StudyPlanChangeAdmin(StudyPlanChange, None)
        request = Mock(user=administrator)
        self.assertFalse(admin.has_add_permission(request))
        self.assertFalse(admin.has_change_permission(request))
        self.assertFalse(admin.has_delete_permission(request))


@override_settings(**CHANGE_SETTINGS)
class PlanChangeClientContractTests(SimpleTestCase):
    def test_schedule_request_uses_explicit_card_authorisation_and_first_debit_date(self):
        when = timezone.now() + timedelta(days=10)
        with patch.object(PaystackLiveClient, "_request", return_value={"subscription_code": "SUB_new"}) as request:
            PaystackLiveClient().create_subscription(customer_code="CUS_owner", plan_code="PLN_growLive", authorization_code="AUTH_fake_test_only", start_date=when)
        self.assertEqual(request.call_args.args, ("POST", "/subscription", {
            "customer": "CUS_owner", "plan": "PLN_growLive", "authorization": "AUTH_fake_test_only", "start_date": when.isoformat(),
        }))

    def test_resume_contract_accepts_empty_success_data_without_creating_a_new_subscription(self):
        with patch.object(PaystackLiveClient, "_request", return_value={}) as request:
            PaystackLiveClient().enable_subscription("SUB_old", "fake_test_token")
        request.assert_called_once_with("POST", "/subscription/enable", {"code": "SUB_old", "token": "fake_test_token"}, allow_empty_data=True)

"""Future-dated billing with fake provider state; never charge a real card."""

from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from .access import get_study_tier
from .downgrade_service import process_downgrade_batch, process_downgrade_change, request_live_downgrade
from .models import StudyMembership, StudyPayment, StudyPlanChange, StudyRefund
from .payment_service import CheckoutNotAllowed
from .paystack_checkout import _one_month_after
from .paystack_client import PaystackError, PaystackLiveClient
from .test_plan_changes import CHANGE_SETTINGS


@override_settings(**CHANGE_SETTINGS)
class DowngradeSchedulingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="schedule-owner", email="schedule@example.com")
        EmailAddress.objects.create(user=self.user, email=self.user.email, primary=True, verified=True)
        self.paid = timezone.now() - timedelta(days=10)
        self.end = _one_month_after(self.paid)
        self.payment = StudyPayment.objects.create(
            user=self.user, tier="bloom", mode="live", source="checkout", plan="monthly", status="succeeded",
            expected_amount_cents=9000, currency="ZAR", checkout_email=self.user.email,
            paystack_plan_code="PLN_bloomLive", paystack_transaction_id=101, verified_at=self.paid,
        )
        StudyPayment.objects.filter(pk=self.payment.pk).update(created_at=self.paid - timedelta(minutes=1))
        self.member = StudyMembership.objects.create(
            user=self.user, tier="bloom", payment_mode="live", plan="monthly", status="active", paid_until=self.end,
            paystack_customer_code="CUS_owner", paystack_subscription_code="SUB_old",
        )
        self.authorization = {"authorization_code": "AUTH_fakeScheduleCard", "reusable": True, "channel": "card"}
        self.charge = {
            "domain": "live", "status": "success", "id": 101, "reference": self.payment.reference,
            "amount": 9000, "currency": "ZAR", "paid_at": self.paid.isoformat(),
            "customer": {"id": 9, "customer_code": "CUS_owner", "email": self.user.email},
            "plan": "PLN_bloomLive", "authorization": deepcopy(self.authorization),
        }
        self.subscriptions = {"SUB_old": {
            "domain": "live", "id": 11, "subscription_code": "SUB_old", "status": "active",
            "customer": {"id": 9, "customer_code": "CUS_owner"},
            "plan": self.plan("PLN_bloomLive"), "email_token": "fake-cancel-token",
            "authorization": deepcopy(self.authorization), "createdAt": self.paid.isoformat(),
        }}
        self.network = self.mock("accounts.paystack_client.build_opener", side_effect=AssertionError("Real billing forbidden"))
        self.verify = self.mock_client("verify", side_effect=lambda ref: deepcopy(self.charge))
        self.fetch_plan = self.mock_client("fetch_plan", side_effect=self.plan)
        self.fetch_subscription = self.mock_client(
            "fetch_subscription", side_effect=lambda code: deepcopy(self.subscriptions[code]),
        )
        self.disable = self.mock_client("disable_subscription", side_effect=self.stop_subscription)
        self.fetch_customer = self.mock_client("fetch_customer", return_value={
            "domain": "live", "id": 9, "customer_code": "CUS_owner",
        })
        self.list_subscriptions = self.mock_client(
            "list_customer_subscriptions", side_effect=lambda pk: deepcopy(list(self.subscriptions.values())),
        )
        self.create = self.mock_client("create_subscription", side_effect=self.create_subscription)
        self.initialize = self.mock_client("initialize", side_effect=AssertionError("No checkout in a downgrade"))
        self.refund = self.mock_client("create_full_refund", side_effect=AssertionError("No downgrade refund"))

    def mock(self, target, **kwargs):
        patched = patch(target, **kwargs)
        self.addCleanup(patched.stop)
        return patched.start()

    def mock_client(self, method, **kwargs):
        patched = patch.object(PaystackLiveClient, method, **kwargs)
        self.addCleanup(patched.stop)
        return patched.start()

    def plan(self, code):
        return {
            "domain": "live", "plan_code": code, "amount": 3500 if code == "PLN_growLive" else 9000,
            "currency": "ZAR", "interval": "monthly", "is_deleted": False, "is_archived": False,
        }

    def stop_subscription(self, code, token):
        self.subscriptions[code]["status"] = "non-renewing"
        return {}

    def create_subscription(self, **data):
        code = "SUB_lower"
        self.subscriptions[code] = {
            "id": 12, "domain": "live", "subscription_code": code, "status": "active", "amount": 3500,
            "customer": {"id": 9, "customer_code": data["customer_code"]},
            "plan": self.plan(data["plan_code"]), "authorization": deepcopy(self.authorization),
            "start": int(data["start_date"].timestamp()), "createdAt": timezone.now().isoformat(),
            "email_token": "fake-lower-cancel-token",
        }
        return {"subscription_code": code}

    def request(self, tier="grow"):
        return request_live_downgrade(user=self.user, tier=tier)

    def process(self, change=None):
        change = change or StudyPlanChange.objects.get(user=self.user)
        StudyPlanChange.objects.filter(pk=change.pk).update(next_attempt_at=None)
        return process_downgrade_change(change.pk)

    def assert_old_paid_access(self):
        self.member.refresh_from_db()
        self.assertEqual((self.member.tier, self.member.paid_until), ("bloom", self.end))
        self.assertEqual(get_study_tier(self.user), "bloom")

    def test_request_records_zero_now_and_35_at_existing_paid_through_date(self):
        change = self.request()
        self.assertEqual((change.kind, change.state, change.from_tier, change.to_tier),
                         ("downgrade", "queued", "bloom", "grow"))
        self.assertEqual((change.amount_due_now_cents, change.monthly_amount_cents, change.effective_at), (0, 3500, self.end))
        self.assertEqual(change.previous_payment_id, self.payment.pk)
        self.assert_old_paid_access()
        self.assertEqual(StudyPayment.objects.count(), 1)
        self.disable.assert_not_called()
        self.create.assert_not_called()
        self.initialize.assert_not_called()
        self.refund.assert_not_called()
        self.network.assert_not_called()

    def test_repeated_identical_request_has_one_saved_instruction(self):
        first, second = self.request(), self.request()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(StudyPlanChange.objects.count(), 1)
        self.create.assert_not_called()

    def test_different_pending_change_must_not_create_two_schedules(self):
        self.request()
        with self.assertRaises(CheckoutNotAllowed):
            self.request("free")
        self.assertEqual(StudyPlanChange.objects.count(), 1)

    def test_only_the_exact_previously_charged_reusable_card_is_selected(self):
        for changes in ({"reusable": False}, {"channel": "bank"}, {"authorization_code": "AUTH_different"}):
            with self.subTest(changes=changes):
                self.charge["authorization"] = {**self.authorization, **changes}
                with self.assertRaises(PaystackError):
                    self.request()
        self.create.assert_not_called()
        self.assertFalse(StudyPlanChange.objects.exists())

    def test_no_card_authorization_or_cancellation_token_is_stored(self):
        change = self.request()
        self.process(change)
        stored = json.dumps({
            "changes": list(StudyPlanChange.objects.values()), "payments": list(StudyPayment.objects.values()),
        }, default=str)
        self.assertNotIn("AUTH_fakeScheduleCard", stored)
        self.assertNotIn("fake-cancel-token", stored)
        self.assertNotIn("fake-lower-cancel-token", stored)
        self.assertEqual(change.authorization_fingerprint, hashlib.sha256(b"AUTH_fakeScheduleCard").hexdigest())

    def test_worker_confirms_old_stop_then_schedules_lower_first_debit_without_changing_paid_tier(self):
        change = self.process(self.request())
        self.assertEqual((change.state, change.to_subscription_code), ("scheduled", "SUB_lower"))
        self.assertIsNotNone(change.old_stopped_at)
        self.assert_old_paid_access()
        self.assertEqual(self.member.status, "non_renewing")
        self.disable.assert_called_once_with("SUB_old", "fake-cancel-token")
        self.create.assert_called_once_with(customer_code="CUS_owner", plan_code="PLN_growLive",
                                            authorization_code="AUTH_fakeScheduleCard", start_date=self.end)
        self.assertEqual(StudyPayment.objects.count(), 1)
        self.assertFalse(StudyRefund.objects.exists())

    def test_current_renewal_supplies_verified_period_and_charged_card(self):
        renewal_start = timezone.now() - timedelta(days=2)
        end = _one_month_after(renewal_start)
        renewal = StudyPayment.objects.create(
            user=self.user, mode="live", tier="bloom", plan="monthly", source="renewal", status="succeeded",
            expected_amount_cents=9000, currency="ZAR", checkout_email=self.user.email,
            paystack_transaction_id=102, verified_at=renewal_start, paystack_plan_code="PLN_bloomLive",
            paystack_subscription_code="SUB_old", paystack_invoice_code="INV_current",
            period_start=renewal_start, period_end=end,
        )
        self.charge.update(reference=renewal.reference, id=102, paid_at=renewal_start.isoformat())
        StudyMembership.objects.filter(pk=self.member.pk).update(paid_until=end)
        change = self.process(self.request())
        self.assertEqual((change.state, change.previous_payment_id, change.effective_at), ("scheduled", renewal.pk, end))
        self.assertEqual(self.create.call_args.kwargs["start_date"], end)

    def test_scheduler_does_not_create_a_subscription_twice(self):
        change = self.process(self.request())
        self.process(change)
        self.create.assert_called_once()
        self.assert_old_paid_access()

    def test_old_cancellation_timeout_after_success_is_confirmed_before_new_schedule(self):
        def timeout(code, token):
            self.stop_subscription(code, token)
            raise PaystackError("fake timeout")
        self.disable.side_effect = timeout
        self.assertEqual(self.process(self.request()).state, "scheduled")
        self.create.assert_called_once()

    def test_unconfirmed_old_cancellation_never_creates_lower_subscription(self):
        self.disable.side_effect = PaystackError("fake timeout")
        change = self.process(self.request())
        self.assertEqual((change.state, change.last_result), ("queued", "lower_provider_confirmation_pending"))
        self.assertGreater(change.next_attempt_at, timezone.now())
        self.create.assert_not_called()
        self.assert_old_paid_access()

    def test_subscription_timeout_before_acceptance_does_not_repeat_financial_post(self):
        self.create.side_effect = PaystackError("fake timeout before acceptance")
        change = self.process(self.request())
        self.assertEqual(change.state, "submitting")
        self.assertIsNotNone(change.subscription_posted_at)
        self.assertEqual(change.subscription_baseline, ["SUB_old"])
        self.assertEqual(self.process(change).state, "submitting")
        self.create.assert_called_once()
        self.assert_old_paid_access()

    def test_subscription_timeout_after_acceptance_recovers_exact_canonical_schedule(self):
        def timeout(**data):
            self.create_subscription(**data)
            raise PaystackError("fake timeout after acceptance")
        self.create.side_effect = timeout
        change = self.process(self.request())
        self.assertEqual(change.state, "submitting")
        recovered = self.process(change)
        self.assertEqual((recovered.state, recovered.to_subscription_code), ("scheduled", "SUB_lower"))
        self.create.assert_called_once()

    def test_wrong_start_price_customer_card_or_mode_is_never_attached(self):
        for changes in (
            {"start": int(self.end.timestamp()) - 60}, {"amount": 1}, {"domain": "test"},
            {"customer": {"customer_code": "CUS_unrelated"}},
            {"authorization": {"authorization_code": "AUTH_other"}},
        ):
            with self.subTest(changes=changes):
                # Each attempt is an isolated transaction, with no real provider.
                with transaction.atomic():
                    self.subscriptions["SUB_old"]["status"] = "active"
                    self.subscriptions.pop("SUB_lower", None)
                    def wrong(**data):
                        result = self.create_subscription(**data)
                        self.subscriptions["SUB_lower"].update(deepcopy(changes))
                        return result
                    self.create.side_effect = wrong
                    result = self.process(self.request())
                    self.assertEqual((result.state, result.last_result), ("attention", "scheduled_subscription_proof_mismatch"))
                    self.assertIsNone(result.to_subscription_code)
                    self.assert_old_paid_access()
                    transaction.set_rollback(True)

    def test_two_identical_new_remote_candidates_require_attention_not_guessing(self):
        def timeout(**data):
            self.create_subscription(**data)
            self.subscriptions["SUB_duplicate"] = {**deepcopy(self.subscriptions["SUB_lower"]),
                                                   "subscription_code": "SUB_duplicate", "id": 13}
            raise PaystackError("fake timeout")
        self.create.side_effect = timeout
        change = self.process(self.request())
        result = self.process(change)
        self.assertEqual((result.state, result.last_result), ("attention", "scheduled_subscription_ambiguous"))
        self.create.assert_called_once()

    def test_preexisting_lower_subscription_cannot_be_adopted_after_timeout(self):
        self.create_subscription(customer_code="CUS_owner", plan_code="PLN_growLive", start_date=self.end)
        self.subscriptions["SUB_lower"]["status"] = "non-renewing"
        self.create.side_effect = PaystackError("fake timeout")
        change = self.process(self.request())
        self.assertIn("SUB_lower", change.subscription_baseline)
        self.assertEqual(self.process(change).state, "submitting")
        self.assertIsNone(StudyPlanChange.objects.get().to_subscription_code)
        self.create.assert_called_once()

    def test_existing_active_lower_subscription_cannot_be_duplicated(self):
        self.create_subscription(customer_code="CUS_owner", plan_code="PLN_growLive", start_date=self.end)
        result = self.process(self.request())
        self.assertEqual((result.state, result.last_result), ("attention", "lower_subscription_already_exists"))
        self.create.assert_not_called()
        self.disable.assert_not_called()

    def test_list_truncation_prevents_creation_and_recovery_guessing(self):
        self.list_subscriptions.side_effect = None
        self.list_subscriptions.return_value = [deepcopy(self.subscriptions["SUB_old"]) for _ in range(100)]
        result = self.process(self.request())
        self.assertEqual((result.state, result.last_result), ("attention", "subscription_list_incomplete"))
        self.create.assert_not_called()

    def test_old_or_new_subscription_owned_by_another_account_is_not_touched(self):
        change = self.request()
        other = get_user_model().objects.create_user(username="another-subscriber")
        StudyMembership.objects.filter(pk=self.member.pk).update(paystack_subscription_code=None)
        StudyMembership.objects.create(user=other, tier="bloom", plan="monthly", paystack_subscription_code="SUB_old")
        self.assertEqual(self.process(change).last_result, "previous_subscription_owned_elsewhere")
        self.disable.assert_not_called()
        self.create.assert_not_called()

    def test_returned_lower_subscription_cannot_be_taken_from_another_membership(self):
        other = get_user_model().objects.create_user(username="lower-subscriber")
        StudyMembership.objects.create(user=other, tier="grow", plan="monthly", paystack_subscription_code="SUB_lower")
        result = self.process(self.request())
        self.assertEqual((result.state, result.last_result), ("attention", "scheduled_subscription_is_current"))
        self.assertIsNone(result.to_subscription_code)
        self.assertEqual(self.subscriptions["SUB_lower"]["status"], "active")

    def test_changed_paid_period_requires_reconciliation_before_scheduling(self):
        change = self.request()
        StudyMembership.objects.filter(pk=self.member.pk).update(paid_until=self.end + timedelta(days=30))
        self.assertEqual(self.process(change).last_result, "downgrade_scope_changed")
        self.disable.assert_not_called()
        self.create.assert_not_called()

    def test_pending_refund_prevents_a_new_future_debit(self):
        change = self.request()
        StudyRefund.objects.create(user=self.user, payment=self.payment, mode="live", amount_cents=9000)
        self.assertEqual(self.process(change).last_result, "scheduled_billing_cleanup_required")
        self.create.assert_not_called()

    def test_inactive_and_permanent_free_accounts_never_schedule_a_new_debit(self):
        change = self.request()
        for values in ({"is_active": False}, {"beta_lifetime_access": True}):
            with self.subTest(values=values):
                get_user_model().objects.filter(pk=self.user.pk).update(**{
                    "is_active": True, "beta_lifetime_access": False, **values,
                })
                StudyPlanChange.objects.filter(pk=change.pk).update(state="queued", next_attempt_at=None)
                self.assertEqual(self.process(change).last_result, "scheduled_billing_cleanup_required")
        self.create.assert_not_called()

    def test_new_plan_wrong_price_is_rejected_before_old_renewals_are_stopped(self):
        change = self.request()
        self.fetch_plan.side_effect = lambda code: {**self.plan(code), "amount": 1}
        result = self.process(change)
        self.assertNotEqual(result.state, "scheduled")
        self.disable.assert_not_called()
        self.create.assert_not_called()

    def test_new_authorization_cannot_replace_the_saved_billing_consent(self):
        change = self.request()
        self.charge["authorization"]["authorization_code"] = "AUTH_changed"
        self.subscriptions["SUB_old"]["authorization"]["authorization_code"] = "AUTH_changed"
        self.assertEqual(self.process(change).last_result, "scheduled_card_or_period_changed")
        self.disable.assert_not_called()
        self.create.assert_not_called()

    def test_account_state_is_rechecked_after_submission_intent_is_saved(self):
        change = self.request()
        def deactivate_during_preparation(customer_id):
            get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
            return deepcopy(list(self.subscriptions.values()))
        self.list_subscriptions.side_effect = deactivate_during_preparation
        result = self.process(change)
        self.assertEqual((result.state, result.last_result), ("attention", "lower_submission_scope_changed"))
        self.assertIsNotNone(result.subscription_posted_at)
        self.create.assert_not_called()

    def test_elapsed_start_date_never_turns_into_an_immediate_subscription_charge(self):
        change = self.request()
        with patch("accounts.downgrade_service.timezone.now", return_value=self.end + timedelta(seconds=1)):
            result = self.process(change)
        self.assertEqual((result.state, result.last_result), ("attention", "lower_start_date_passed"))
        self.create.assert_not_called()
        self.disable.assert_not_called()

    def test_uncertain_submission_is_only_get_reconciled_even_after_start_date(self):
        self.create.side_effect = PaystackError("fake timeout")
        change = self.process(self.request())
        with patch("accounts.downgrade_service.timezone.now", return_value=self.end + timedelta(seconds=1)):
            result = self.process(change)
        self.assertEqual((result.state, result.last_result), ("attention", "lower_subscription_needs_attention"))
        self.create.assert_called_once()

    def test_scheduled_paid_plan_does_not_unlock_grow_just_because_date_arrived(self):
        change = self.process(self.request())
        with patch("accounts.downgrade_service.timezone.now", return_value=self.end + timedelta(seconds=1)):
            result = self.process(change)
            self.assertEqual(result.last_result, "awaiting_verified_lower_payment")
            self.assertEqual(get_study_tier(self.user), "free")
        self.assertEqual(StudyPayment.objects.count(), 1)
        self.create.assert_called_once()

    def test_free_downgrade_needs_no_reusable_card_or_new_subscription(self):
        self.charge.pop("authorization")
        self.subscriptions["SUB_old"].pop("authorization")
        change = self.process(self.request("free"))
        self.assertEqual((change.state, change.to_tier, change.monthly_amount_cents), ("scheduled", "free", 0))
        self.assert_old_paid_access()
        self.assertEqual(self.member.status, "non_renewing")
        self.create.assert_not_called()
        self.fetch_customer.assert_not_called()

    def test_grow_to_free_also_keeps_its_remaining_paid_month(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(tier="grow")
        StudyPayment.objects.filter(pk=self.payment.pk).update(tier="grow", expected_amount_cents=3500,
                                                              paystack_plan_code="PLN_growLive")
        self.charge.update(amount=3500, plan="PLN_growLive")
        self.subscriptions["SUB_old"]["plan"] = self.plan("PLN_growLive")
        result = self.process(self.request("free"))
        self.assertEqual((result.state, result.from_tier, result.to_tier), ("scheduled", "grow", "free"))
        self.assertEqual(get_study_tier(self.user), "grow")
        self.assertEqual(StudyMembership.objects.get().paid_until, self.end)
        self.create.assert_not_called()

    def test_a_future_scheduled_change_is_not_processed_before_its_due_time(self):
        change = self.process(self.request())
        self.fetch_subscription.reset_mock()
        result = process_downgrade_change(change.pk)
        self.assertEqual(result.state, "scheduled")
        self.fetch_subscription.assert_not_called()
        self.create.assert_called_once()

    def test_free_becomes_effective_at_paid_end_without_deleting_or_charging(self):
        change = self.process(self.request("free"))
        with patch("accounts.downgrade_service.timezone.now", return_value=self.end + timedelta(seconds=1)):
            self.assertEqual(self.process(change).state, "applied")
            self.assertEqual(get_study_tier(self.user), "free")
        self.assertEqual(StudyPayment.objects.count(), 1)
        self.assertEqual(StudyMembership.objects.get().paid_until, self.end)
        self.create.assert_not_called()
        self.refund.assert_not_called()

    def test_already_non_renewing_paid_access_stays_available_during_free_downgrade(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(status="non_renewing")
        self.subscriptions["SUB_old"]["status"] = "non-renewing"
        self.assertEqual(self.process(self.request("free")).state, "scheduled")
        self.disable.assert_not_called()
        self.assert_old_paid_access()

    def test_new_sales_pause_does_not_block_free_cancellation(self):
        with override_settings(PAYSTACK_LIVE_CHECKOUT_ENABLED=False):
            change = self.request("free")
            self.assertEqual(self.process(change).state, "scheduled")
        self.create.assert_not_called()

    def test_accepted_instruction_continues_when_new_plan_changes_are_paused(self):
        self.request()
        with override_settings(PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False, PAYSTACK_LIVE_CHECKOUT_ENABLED=False):
            result = process_downgrade_batch()
        self.assertEqual(result[0][1], "scheduled")
        self.create.assert_called_once()

    def test_unknown_plan_test_mode_and_disabled_changes_fail_closed(self):
        with self.assertRaises(CheckoutNotAllowed):
            self.request("unknown")
        with override_settings(PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False), self.assertRaises(CheckoutNotAllowed):
            self.request()
        StudyMembership.objects.filter(pk=self.member.pk).update(payment_mode="test")
        with self.assertRaises(CheckoutNotAllowed):
            self.request()
        self.create.assert_not_called()
        self.disable.assert_not_called()

    def test_cancel_requested_never_submits_a_new_subscription(self):
        change = self.request()
        StudyPlanChange.objects.filter(pk=change.pk).update(cancel_requested=True)
        self.assertEqual(self.process(change).last_result, "scheduled_billing_cleanup_required")
        self.create.assert_not_called()

    def test_ambiguous_submission_unresolved_for_a_day_is_visible_for_attention(self):
        self.create.side_effect = PaystackError("fake timeout")
        change = self.process(self.request())
        StudyPlanChange.objects.filter(pk=change.pk).update(subscription_posted_at=timezone.now() - timedelta(hours=25))
        result = self.process(change)
        self.assertEqual((result.state, result.last_result), ("attention", "lower_subscription_needs_attention"))
        self.create.assert_called_once()

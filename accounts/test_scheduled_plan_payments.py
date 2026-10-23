"""Scheduled debits, cancellation and retired-charge refunds; fake provider only."""

from copy import deepcopy
from datetime import timedelta
import hashlib
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from . import test_downgrade_scheduling as fixtures
from .access import get_study_tier
from .downgrade_cancellation import request_schedule_cancellation
from .downgrade_service import process_downgrade_batch
from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment, StudyPlanChange, StudyRefund
from .payment_service import CheckoutNotAllowed
from .payment_webhooks import process_live_payment_receipt
from .paystack_checkout import _one_month_after, live_checkout_page_context
from .paystack_client import PaystackError, PaystackLiveClient, PaystackTestClient
from .refund_service import process_live_refund, request_first_payment_refund
from .subscription_service import cancel_live_membership
from .subscription_webhooks import process_live_subscription_receipt
from .test_plan_changes import CHANGE_SETTINGS
from .upgrade_service import prepare_live_upgrade


@override_settings(**CHANGE_SETTINGS)
class ScheduledPlanPaymentTests(TestCase):
    # Reuse the stateful fake, without inheriting and rediscovering its tests.
    mock = fixtures.DowngradeSchedulingTests.mock
    mock_client = fixtures.DowngradeSchedulingTests.mock_client
    plan = fixtures.DowngradeSchedulingTests.plan
    stop_subscription = fixtures.DowngradeSchedulingTests.stop_subscription
    create_subscription = fixtures.DowngradeSchedulingTests.create_subscription
    request = fixtures.DowngradeSchedulingTests.request
    process = fixtures.DowngradeSchedulingTests.process
    assert_old_paid_access = fixtures.DowngradeSchedulingTests.assert_old_paid_access

    def setUp(self):
        fixtures.DowngradeSchedulingTests.setUp(self)
        self.charges = {self.payment.reference: deepcopy(self.charge)}
        self.verify.side_effect = lambda ref: deepcopy(self.charges[ref])
        self.subscriptions["SUB_old"]["next_payment_date"] = self.end.isoformat()
        self.subscriptions["SUB_old"]["amount"] = 9000
        self.enable = self.mock_client("enable_subscription", side_effect=lambda code, token:
                                      self.subscriptions[code].update(status="active"))
        self.fetch_transaction = self.mock_client("fetch_transaction", side_effect=lambda tx:
                                                deepcopy(next(c for c in self.charges.values() if c["id"] == tx)))
        self.refunds = {}
        self.refund.side_effect = self.submit_refund
        self.mock_client("list_refunds", side_effect=lambda tx: deepcopy([
            r for r in self.refunds.values() if r["transaction"] == tx
        ]))
        self.mock_client("fetch_refund", side_effect=lambda pk: deepcopy(self.refunds[pk]))

    def submit_refund(self, tx, amount, note, **kwargs):
        pk = 901 + len(self.refunds)
        self.refunds[pk] = {"id": pk, "domain": "live", "transaction": tx, "amount": amount,
                            "currency": "ZAR", "status": "processing"}
        return deepcopy(self.refunds[pk])

    def clock(self, when=None):
        return patch("accounts.plan_change_payments.timezone.now", return_value=when or self.end + timedelta(seconds=5))

    def invoice(self, *, code="SUB_lower", start=None, tx=202, successful=True):
        start = start or self.end
        end = _one_month_after(start)
        sub = self.subscriptions[code]
        amount = 3500 if code == "SUB_lower" else 9000
        reference = f"scheduled-debit-{tx}"
        invoice_code = f"INV_debit{tx}"
        sub["status"] = sub["status"] if successful else "attention"
        sub["most_recent_invoice"] = {
            "id": tx + 100, "domain": "live", "invoice_code": invoice_code, "subscription": sub["id"],
            "customer": 9, "amount": amount, "currency": "ZAR", "paid": successful,
            "status": "success" if successful else "failed", "transaction": tx if successful else None,
            "period_start": start.isoformat(), "period_end": end.isoformat(),
        }
        self.charges[reference] = {
            "id": tx, "reference": reference, "domain": "live", "status": "success", "amount": amount,
            "currency": "ZAR", "plan": sub["plan"]["plan_code"], "paid_at": start.isoformat(),
            "customer": {"id": 9, "customer_code": "CUS_owner", "email": self.user.email},
            "authorization": deepcopy(self.authorization),
        }
        return {
            "schema_version": 1, "domain": "live", "subscription_code": code,
            "plan_code": sub["plan"]["plan_code"], "customer_code": "CUS_owner", "invoice_code": invoice_code,
            "amount_cents": amount, "currency": "ZAR", "transaction_id": tx if successful else None,
            "transaction_reference": reference if successful else None,
            "period_start": start.isoformat(), "period_end": end.isoformat(),
        }

    def receipt(self, snapshot, event="invoice.update"):
        return PaystackWebhookReceipt.objects.create(
            mode="live", event_type=event, snapshot=deepcopy(snapshot),
            payload_sha256=hashlib.sha256(str(PaystackWebhookReceipt.objects.count()).encode()).hexdigest(),
        )

    def paid_lower(self):
        self.process(self.request())
        with self.clock():
            result = process_live_payment_receipt(self.receipt(self.invoice()).pk)
        self.assertEqual(result.last_result, "lower_payment_verified")
        return StudyPlanChange.objects.get(user=self.user)

    def cancel(self, change, *, restore=False):
        request_schedule_cancellation(user=self.user, change_id=change.pk, restore_current=restore)
        return self.process(change)

    def refund_one(self):
        refund = StudyRefund.objects.get(reason="retired_subscription")
        StudyRefund.objects.filter(pk=refund.pk).update(next_attempt_at=None)
        return process_live_refund(refund.pk)

    def test_verified_first_debit_switches_to_grow_and_stores_renewal_proof(self):
        change = self.paid_lower()
        self.member.refresh_from_db()
        self.assertEqual((self.member.tier, self.member.status, self.member.paystack_subscription_code),
                         ("grow", "active", "SUB_lower"))
        self.assertEqual(self.member.paid_until, _one_month_after(self.end))
        self.assertEqual((change.state, change.payment.source, change.payment.tier), ("applied", "renewal", "grow"))
        self.assertEqual(StudyPayment.objects.count(), 2)
        self.assertFalse(StudyRefund.objects.exists())

    def test_subscription_metadata_does_not_switch_tier_or_grant_time(self):
        self.process(self.request())
        receipt = self.receipt({"schema_version": 1, "domain": "live", "subscription_code": "SUB_lower"},
                               "subscription.create")
        self.assertEqual(process_live_subscription_receipt(receipt.pk).last_result, "scheduled_subscription_metadata_only")
        self.assert_old_paid_access()
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_duplicate_first_invoice_does_not_extend_access_again(self):
        self.paid_lower()
        with self.clock():
            result = process_live_payment_receipt(self.receipt(self.invoice()).pk)
        self.assertEqual(result.last_result, "payment_already_recorded")
        self.assertEqual(StudyPayment.objects.count(), 2)
        self.assertEqual(StudyMembership.objects.get().paid_until, _one_month_after(self.end))

    def test_failed_first_debit_does_not_grant_grow_or_remove_remaining_bloom_time(self):
        self.process(self.request())
        with self.clock():
            result = process_live_payment_receipt(self.receipt(self.invoice(successful=False), "invoice.payment_failed").pk)
            self.assertEqual(get_study_tier(self.user), "free")
        self.assertEqual(result.last_result, "scheduled_payment_failed")
        self.assertEqual(StudyMembership.objects.get().paid_until, self.end)
        self.assertEqual(StudyPayment.objects.get(source="renewal").status, "failed")

    def test_failed_then_successful_invoice_can_be_verified_once(self):
        self.process(self.request())
        with self.clock():
            process_live_payment_receipt(self.receipt(self.invoice(successful=False), "invoice.payment_failed").pk)
            self.subscriptions["SUB_lower"]["status"] = "active"
            result = process_live_payment_receipt(self.receipt(self.invoice()).pk)
        self.assertEqual(result.last_result, "lower_payment_verified")
        self.assertEqual(StudyPayment.objects.filter(source="renewal").count(), 1)

    def test_missing_notification_reference_is_resolved_by_canonical_transaction_get(self):
        self.process(self.request())
        with self.clock():
            snapshot = self.invoice()
            snapshot.pop("transaction_reference")
            result = process_live_payment_receipt(self.receipt(snapshot).pk)
        self.assertEqual(result.last_result, "lower_payment_verified")
        self.fetch_transaction.assert_called_once_with(202)

    def test_wrong_verified_amount_is_ignored_without_granting_access(self):
        self.process(self.request())
        with self.clock():
            snapshot = self.invoice()
            self.charges[snapshot["transaction_reference"]]["amount"] = 1
            result = process_live_payment_receipt(self.receipt(snapshot).pk)
        self.assertEqual((result.processing_status, result.last_result), ("ignored", "transaction_mismatch"))
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_later_grow_renewals_use_scheduled_first_debit_as_payment_proof(self):
        self.paid_lower()
        start = _one_month_after(self.end)
        with self.clock(start + timedelta(seconds=5)):
            result = process_live_payment_receipt(self.receipt(self.invoice(start=start, tx=203)).pk)
        self.assertEqual(result.last_result, "renewal_verified")
        self.assertEqual(StudyMembership.objects.get().paid_until, _one_month_after(start))

    def test_cancellation_of_grow_after_first_debit_keeps_its_already_paid_month(self):
        self.paid_lower()
        with self.clock():
            member = cancel_live_membership(user=self.user)
        self.assertEqual((member.tier, member.status, member.paid_until), ("grow", "non_renewing", _one_month_after(self.end)))
        self.assertEqual(self.subscriptions["SUB_lower"]["status"], "non-renewing")
        self.assertFalse(StudyRefund.objects.exists())

    def test_upgrade_from_scheduled_grow_uses_its_current_renewal_as_funding(self):
        change = self.paid_lower()
        self.initialize.side_effect = lambda data: {"reference": data["reference"],
                                                   "authorization_url": "https://checkout.paystack.com/fake-upgrade"}
        with self.clock():
            payment = prepare_live_upgrade(user=self.user)
        upgrade = StudyPlanChange.objects.get(kind="upgrade")
        self.assertEqual((payment.tier, upgrade.previous_payment_id), ("bloom", change.payment_id))
        self.assertEqual(upgrade.from_subscription_code, "SUB_lower")

    def test_cancel_scheduled_lower_stops_both_renewals_but_keeps_bloom_paid_time(self):
        change = self.process(self.request())
        result = self.cancel(change)
        self.assertEqual((result.state, result.last_result), ("cancelled", "scheduled_renewals_stopped"))
        self.assertIsNotNone(result.cancel_requested_at)
        self.assertIsNotNone(result.cancelled_at)
        self.assertEqual(self.subscriptions["SUB_lower"]["status"], "non-renewing")
        self.assertEqual(self.subscriptions["SUB_old"]["status"], "non-renewing")
        self.assert_old_paid_access()
        self.assertEqual(self.member.status, "non_renewing")

    def test_normal_cancel_button_also_stops_the_scheduled_replacement(self):
        self.process(self.request())
        member = cancel_live_membership(user=self.user)
        self.assertEqual(member.status, "non_renewing")
        self.assertEqual(self.subscriptions["SUB_lower"]["status"], "non-renewing")
        self.assertIsNotNone(StudyPlanChange.objects.get().cancelled_at)

    def test_explicit_cancel_switch_can_resume_bloom_without_charging_now(self):
        change = self.process(self.request())
        result = self.cancel(change, restore=True)
        self.assertEqual((result.state, result.last_result), ("cancelled", "previous_plan_resumed"))
        self.assert_old_paid_access()
        self.assertEqual(self.member.status, "active")
        self.enable.assert_called_once_with("SUB_old", "fake-cancel-token")
        self.create.assert_called_once()

    def test_uncertain_new_subscription_is_reconciled_then_cancelled_without_second_create(self):
        def timeout(**data):
            self.create_subscription(**data)
            raise PaystackError("fake timeout after acceptance")
        self.create.side_effect = timeout
        change = self.process(self.request())
        self.assertEqual(change.state, "submitting")
        result = self.cancel(change)
        self.assertEqual(result.state, "cancelled")
        self.assertEqual(self.subscriptions["SUB_lower"]["status"], "non-renewing")
        self.create.assert_called_once()

    def test_cancellation_timeout_before_acceptance_is_not_reported_as_stopped(self):
        change = self.process(self.request())
        self.disable.side_effect = PaystackError("fake cancellation timeout")
        result = self.cancel(change)
        self.assertIsNone(result.cancelled_at)
        self.assertEqual(result.state, "scheduled")
        self.assertTrue(result.cancel_requested)

    def test_already_paid_lower_month_is_kept_when_notification_arrives_after_cancel(self):
        change = self.process(self.request())
        with self.clock():
            snapshot = self.invoice()
            self.cancel(change)
            result = process_live_payment_receipt(self.receipt(snapshot).pk)
        self.assertEqual(result.last_result, "lower_payment_verified")
        self.assertEqual(StudyMembership.objects.get().tier, "grow")
        self.assertEqual(StudyMembership.objects.get().status, "non_renewing")
        self.assertFalse(StudyRefund.objects.exists())

    def test_lower_charge_after_cancel_is_refunded_without_replacing_bloom(self):
        change = self.process(self.request())
        self.cancel(change)
        with self.clock():
            result = process_live_payment_receipt(self.receipt(self.invoice()).pk)
            refund = self.refund_one()
        self.assertEqual(result.last_result, "cancelled_lower_payment_refund_queued")
        self.assertEqual(refund.status, "processing")
        self.assertEqual(self.refund.call_args.args[:2], (202, 3500))
        self.assertEqual(StudyMembership.objects.get().tier, "bloom")

    def test_late_charge_does_not_undo_an_explicit_resume_of_bloom(self):
        change = self.process(self.request())
        self.cancel(change, restore=True)
        with self.clock():
            process_live_payment_receipt(self.receipt(self.invoice()).pk)
            self.refund_one()
        self.assertEqual(self.subscriptions["SUB_old"]["status"], "active")
        self.assertTrue(StudyPlanChange.objects.get().restore_current)

    def test_stopped_bloom_renewal_is_returned_without_cancelling_chosen_grow(self):
        self.paid_lower()
        with self.clock():
            result = process_live_payment_receipt(self.receipt(self.invoice(code="SUB_old", tx=303)).pk)
            refund = self.refund_one()
            self.refunds[refund.paystack_refund_id]["status"] = "processed"
            completed = self.refund_one()
        self.assertEqual((result.last_result, completed.status), ("retired_payment_refund_queued", "completed"))
        self.assertEqual(self.refund.call_args.args[:2], (303, 9000))
        self.assertEqual(self.subscriptions["SUB_lower"]["status"], "active")
        self.assertEqual(StudyMembership.objects.get().tier, "grow")

    def test_retired_charge_redelivery_never_returns_the_same_money_twice(self):
        self.paid_lower()
        with self.clock():
            snapshot = self.invoice(code="SUB_old", tx=303)
            process_live_payment_receipt(self.receipt(snapshot).pk)
            self.refund_one()
            process_live_payment_receipt(self.receipt(snapshot).pk)
        self.assertEqual(StudyRefund.objects.count(), 1)
        self.refund.assert_called_once()

    def test_pending_guarantee_waits_for_eligibility_without_switching_or_charging(self):
        change = self.process(self.request())
        request_first_payment_refund(self.user)
        result = self.process(change)
        self.assertEqual(result.last_result, "refund_eligibility_pending")
        self.assertFalse(result.cancel_requested)
        self.create.assert_called_once()

    def test_ineligible_guarantee_does_not_cancel_the_scheduled_plan(self):
        change = self.process(self.request())
        refund = request_first_payment_refund(self.user)
        self.assertEqual(process_live_refund(refund.pk).status, "ineligible")
        self.assertFalse(StudyPlanChange.objects.get().cancel_requested)
        self.assertEqual(self.process(change).state, "scheduled")

    def test_other_user_cannot_cancel_this_schedule(self):
        change = self.process(self.request())
        other = get_user_model().objects.create_user(username="another-account")
        with self.assertRaises(CheckoutNotAllowed):
            request_schedule_cancellation(user=other, change_id=change.pk)
        self.assertFalse(StudyPlanChange.objects.get().cancel_requested)

    def test_resuming_old_plan_is_not_allowed_after_its_paid_month_has_ended(self):
        change = self.process(self.request())
        with self.clock(), self.assertRaises(CheckoutNotAllowed):
            request_schedule_cancellation(user=self.user, change_id=change.pk, restore_current=True)
        self.enable.assert_not_called()

    def test_worker_processes_accepted_schedules_with_new_switch_controls_paused(self):
        self.request()
        with override_settings(PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False, PAYSTACK_LIVE_CHECKOUT_ENABLED=False):
            call_command("process_paystack_live_events", once=True, stdout=io.StringIO())
        self.assertEqual(StudyPlanChange.objects.get().state, "scheduled")
        self.create.assert_called_once()

    def test_profile_can_cancel_future_grow_even_while_current_bloom_is_non_renewing(self):
        change = self.process(self.request())
        request = RequestFactory().get("/my-plan/", secure=True, HTTP_HOST="studigarden.com")
        request.user = self.user
        context = live_checkout_page_context(request)
        self.assertTrue(context["can_cancel_live_membership"])
        self.assertFalse(context["live_renewals_cancelled"])
        self.assertEqual(context["pending_plan_change"].pk, change.pk)

    def test_profile_can_cancel_grow_funded_by_a_scheduled_debit(self):
        self.paid_lower()
        request = RequestFactory().get("/my-plan/", secure=True, HTTP_HOST="studigarden.com")
        request.user = self.user
        with self.clock():
            self.assertTrue(live_checkout_page_context(request)["can_cancel_live_membership"])

    def test_an_early_lower_charge_is_returned_instead_of_shortening_bloom(self):
        self.process(self.request())
        now = timezone.now()
        snapshot = self.invoice(start=now)
        result = process_live_payment_receipt(self.receipt(snapshot).pk)
        self.assertEqual(result.last_result, "cancelled_lower_payment_refund_queued")
        self.assert_old_paid_access()
        self.assertEqual(self.refund_one().status, "processing")
        self.assertEqual(self.refund.call_args.args[:2], (202, 3500))

    def test_retired_refund_timeout_does_not_repeat_the_financial_post(self):
        self.paid_lower()
        with self.clock():
            process_live_payment_receipt(self.receipt(self.invoice(code="SUB_old", tx=303)).pk)
            self.refund.side_effect = PaystackError("fake ambiguous refund POST")
            self.assertEqual(self.refund_one().status, "submitting")
            self.assertEqual(self.refund_one().status, "submitting")
        self.refund.assert_called_once()

    def test_changed_subscription_customer_cannot_trigger_the_lower_tier(self):
        self.process(self.request())
        with self.clock():
            snapshot = self.invoice()
            self.subscriptions["SUB_lower"]["customer"]["customer_code"] = "CUS_unrelated"
            result = process_live_payment_receipt(self.receipt(snapshot).pk)
        self.assertEqual(result.processing_status, "ignored")
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_wrong_live_mode_is_rejected_before_scheduled_payment_processing(self):
        self.process(self.request())
        with self.clock():
            snapshot = self.invoice()
            self.subscriptions["SUB_lower"]["domain"] = "test"
            result = process_live_payment_receipt(self.receipt(snapshot).pk)
        self.assertEqual(result.last_result, "provider_mode_mismatch")
        self.assertEqual(StudyPayment.objects.count(), 1)

    def test_transaction_fetch_uses_a_fixed_read_only_endpoint_and_rejects_invalid_ids(self):
        client = PaystackLiveClient()
        with patch.object(PaystackLiveClient, "_request", return_value={}) as request:
            PaystackTestClient.fetch_transaction(client, 202)
            request.assert_called_once_with("GET", "/transaction/202")
            for value in (True, 0, -1, "202", None):
                with self.subTest(value=value), self.assertRaises(PaystackError):
                    PaystackTestClient.fetch_transaction(client, value)

    def test_approved_first_refund_stops_the_scheduled_lower_subscription_before_returning_money(self):
        self.paid = timezone.now() - timedelta(days=1)
        self.end = _one_month_after(self.paid)
        StudyPayment.objects.filter(pk=self.payment.pk).update(created_at=self.paid - timedelta(minutes=1),
                                                              verified_at=self.paid)
        StudyMembership.objects.filter(pk=self.member.pk).update(paid_until=self.end)
        self.charges[self.payment.reference]["paid_at"] = self.paid.isoformat()
        self.subscriptions["SUB_old"]["next_payment_date"] = self.end.isoformat()
        self.process(self.request())
        refund = request_first_payment_refund(self.user)
        result = process_live_refund(refund.pk)
        self.assertEqual(result.status, "processing")
        self.assertEqual(self.subscriptions["SUB_lower"]["status"], "non-renewing")
        self.assertIsNotNone(StudyPlanChange.objects.get().cancelled_at)
        self.assertEqual(self.refund.call_args.args[:2], (101, 9000))

    def test_a_transaction_already_owned_by_another_payment_cannot_fund_the_downgrade(self):
        self.process(self.request())
        with self.clock():
            result = process_live_payment_receipt(self.receipt(self.invoice(tx=101)).pk)
        self.assertEqual(result.last_result, "plan_change_invoice_already_owned")
        self.assertEqual(StudyPayment.objects.count(), 1)
        self.assertEqual(StudyMembership.objects.get().tier, "bloom")

    def test_a_transition_between_lookup_and_apply_cannot_extend_retired_paid_access(self):
        change = self.process(self.request())
        with self.clock():
            snapshot = self.invoice(code="SUB_old", tx=303)
            receipt = self.receipt(snapshot)
            with patch("accounts.plan_change_payments._retired_from_change", side_effect=[None, change]):
                result = process_live_payment_receipt(receipt.pk)
            self.assertEqual(result.last_result, "plan_change_reconciliation_required")
            self.assertEqual(StudyPayment.objects.count(), 1)
            self.assertEqual(StudyMembership.objects.get().paid_until, self.end)
            PaystackWebhookReceipt.objects.filter(pk=receipt.pk).update(next_attempt_at=None)
            self.assertEqual(process_live_payment_receipt(receipt.pk).last_result, "retired_payment_refund_queued")

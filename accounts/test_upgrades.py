"""Upgrade settlement with a stateful fake provider. Real network is forbidden."""

from copy import deepcopy
from datetime import timedelta
import io
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from .access import get_study_tier
from .models import PaystackWebhookReceipt, StudyMembership, StudyPayment, StudyPlanChange, StudyRefund
from .payment_service import CheckoutNotAllowed
from .payment_webhooks import process_live_payment_receipt
from .paystack_checkout import (
    PaymentNotFound, _one_month_after, initialize_live_checkout, verify_live_checkout,
)
from .paystack_client import PaystackError, PaystackLiveClient
from .refund_service import (
    RefundNotAllowed, process_live_refund, refund_page_context, request_first_payment_refund,
)
from .test_plan_changes import CHANGE_SETTINGS
from .upgrade_service import prepare_live_upgrade, process_upgrade_batch, process_upgrade_change


@override_settings(**CHANGE_SETTINGS)
class UpgradeSettlementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="upgrade-owner", email="upgrade@example.com")
        EmailAddress.objects.create(user=self.user, email=self.user.email, primary=True, verified=True)
        self.old_paid = timezone.now() - timedelta(days=10)
        self.old = StudyPayment.objects.create(
            user=self.user, mode="live", source="checkout", tier="grow", plan="monthly", status="succeeded",
            expected_amount_cents=3500, currency="ZAR", checkout_email=self.user.email,
            paystack_plan_code="PLN_growLive", paystack_transaction_id=101, verified_at=self.old_paid,
        )
        StudyPayment.objects.filter(pk=self.old.pk).update(created_at=self.old_paid - timedelta(minutes=1))
        self.old.refresh_from_db()
        self.member = StudyMembership.objects.create(
            user=self.user, tier="grow", payment_mode="live", plan="monthly", status="active",
            paid_until=_one_month_after(self.old_paid), paystack_customer_code="CUS_owner",
            paystack_subscription_code="SUB_old",
        )
        self.charges = {self.old.reference: self.charge(self.old, self.old_paid, 101)}
        self.subscriptions = {"SUB_old": self.subscription("SUB_old", "PLN_growLive", self.old_paid)}
        self.refunds = {}
        self.network = self.mock("accounts.paystack_client.build_opener", side_effect=AssertionError("Real billing forbidden"))
        self.fetch_plan = self.mock_client("fetch_plan", side_effect=self.plan)
        self.initialize = self.mock_client("initialize", side_effect=lambda data: {
            "reference": data["reference"], "authorization_url": "https://checkout.paystack.com/fake-upgrade",
        })
        self.verify = self.mock_client("verify", side_effect=self.verify_charge)
        self.fetch_subscription = self.mock_client(
            "fetch_subscription", side_effect=lambda code: deepcopy(self.subscriptions[code]),
        )
        self.disable = self.mock_client("disable_subscription", side_effect=self.disable_subscription)
        self.fetch_customer = self.mock_client("fetch_customer", return_value={
            "domain": "live", "id": 9, "customer_code": "CUS_owner",
        })
        self.list_subscriptions = self.mock_client(
            "list_customer_subscriptions", side_effect=lambda customer: deepcopy(list(self.subscriptions.values())),
        )
        self.list_refunds = self.mock_client(
            "list_refunds", side_effect=lambda tx: deepcopy([r for r in self.refunds.values() if r["transaction"] == tx]),
        )
        self.create_refund = self.mock_client("create_full_refund", side_effect=self.submit_refund)
        self.fetch_refund = self.mock_client("fetch_refund", side_effect=lambda pk: deepcopy(self.refunds[pk]))

    def mock(self, target, **kwargs):
        patched = patch(target, **kwargs)
        self.addCleanup(patched.stop)
        return patched.start()

    def mock_client(self, method, **kwargs):
        patched = patch.object(PaystackLiveClient, method, **kwargs)
        self.addCleanup(patched.stop)
        return patched.start()

    def charge(self, payment, paid_at, tx):
        return {
            "domain": "live", "status": "success", "id": tx, "reference": payment.reference,
            "amount": payment.expected_amount_cents, "currency": "ZAR", "paid_at": paid_at.isoformat(),
            "customer": {"customer_code": "CUS_owner", "email": payment.checkout_email},
            "plan": payment.paystack_plan_code,
        }

    def subscription(self, code, plan, created):
        return {
            "domain": "live", "subscription_code": code, "status": "active", "id": 12,
            "customer": {"id": 9, "customer_code": "CUS_owner"},
            "plan": {"domain": "live", "plan_code": plan}, "email_token": "fake-cancel-token",
            "createdAt": created.isoformat(),
        }

    def plan(self, code):
        return {
            "domain": "live", "plan_code": code, "currency": "ZAR", "interval": "monthly",
            "amount": 9000 if code == "PLN_bloomLive" else 3500,
            "is_deleted": False, "is_archived": False,
        }

    def verify_charge(self, reference):
        return deepcopy(self.charges.get(reference, {
            "domain": "live", "reference": reference, "status": "abandoned",
            "customer": {"customer_code": "CUS_owner", "email": self.user.email},
        }))

    def disable_subscription(self, code, token):
        self.subscriptions[code]["status"] = "non-renewing"
        return {}

    def submit_refund(self, tx, amount, note, **kwargs):
        pk = 901 + len(self.refunds)
        self.refunds[pk] = {
            "id": pk, "domain": "live", "transaction": tx, "amount": amount,
            "currency": "ZAR", "status": "processing",
        }
        return deepcopy(self.refunds[pk])

    def start(self):
        return prepare_live_upgrade(user=self.user)

    def pay(self, payment=None, *, paid_at=None, tx=202):
        payment = payment or self.start()
        paid_at = paid_at or timezone.now()
        self.charges[payment.reference] = self.charge(payment, paid_at, tx)
        self.subscriptions["SUB_new"] = self.subscription("SUB_new", "PLN_bloomLive", paid_at)
        self.subscriptions["SUB_new"]["invoices"] = [{"transaction": tx}]
        return verify_live_checkout(user=self.user, reference=payment.reference)

    def settle(self):
        change = StudyPlanChange.objects.get(user=self.user)
        StudyPlanChange.objects.filter(pk=change.pk).update(next_attempt_at=None)
        return process_upgrade_change(change.pk)

    def process_refund(self, refund=None):
        refund = refund or StudyRefund.objects.get(reason="upgrade")
        StudyRefund.objects.filter(pk=refund.pk).update(next_attempt_at=None)
        return process_live_refund(refund.pk)

    def assert_grow_unchanged(self):
        self.member.refresh_from_db()
        self.assertEqual((self.member.tier, self.member.paid_until, self.member.paystack_subscription_code),
                         ("grow", _one_month_after(self.old_paid), "SUB_old"))

    def test_unpaid_upgrade_keeps_grow_and_does_not_stop_or_refund_it(self):
        payment = self.start()
        self.assertEqual((payment.tier, payment.expected_amount_cents, payment.status), ("bloom", 9000, "pending"))
        self.assert_grow_unchanged()
        self.assertEqual(get_study_tier(self.user), "grow")
        self.disable.assert_not_called()
        self.create_refund.assert_not_called()
        self.assertFalse(StudyRefund.objects.exists())
        self.network.assert_not_called()

    def test_checkout_saves_canonical_period_and_server_selected_price(self):
        payment = self.start()
        change = StudyPlanChange.objects.get()
        self.old.refresh_from_db()
        self.assertEqual((change.previous_payment_id, change.from_subscription_code, change.from_paid_until),
                         (self.old.pk, "SUB_old", self.member.paid_until))
        self.assertEqual((self.old.period_start, self.old.period_end, self.old.paystack_subscription_code),
                         (self.old_paid, self.member.paid_until, "SUB_old"))
        data = self.initialize.call_args.args[0]
        self.assertEqual((data["amount"], data["plan"], data["reference"]), (9000, "PLN_bloomLive", payment.reference))
        self.assertEqual(data["callback_url"], "https://studigarden.com/payments/paystack/return/")

    def test_repeated_click_resumes_one_unpaid_checkout(self):
        first = self.start()
        second = self.start()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(StudyPayment.objects.count(), 2)
        self.assertEqual(StudyPlanChange.objects.count(), 1)
        self.initialize.assert_called_once()

    def test_initialize_timeout_keeps_unique_reference_and_old_access(self):
        self.initialize.side_effect = PaystackError("fake timeout")
        with self.assertRaises(PaystackError):
            self.start()
        payment = StudyPayment.objects.get(tier="bloom")
        self.assertEqual(payment.status, "created")
        self.assert_grow_unchanged()
        self.initialize.side_effect = lambda data: {
            "reference": data["reference"], "authorization_url": "https://checkout.paystack.com/fake-upgrade",
        }
        self.assertEqual(self.start().pk, payment.pk)
        self.assertEqual({call.args[0]["reference"] for call in self.initialize.call_args_list}, {payment.reference})

    def test_wrong_remote_plan_price_cannot_redirect_to_checkout(self):
        self.fetch_plan.side_effect = lambda code: {**self.plan(code), "amount": 1}
        with self.assertRaises(PaystackError):
            self.start()
        self.initialize.assert_not_called()
        self.assert_grow_unchanged()

    def test_funding_owner_mode_or_price_mismatch_blocks_upgrade(self):
        for field, value in (("domain", "test"), ("amount", 1), ("customer", {
            "customer_code": "CUS_other", "email": self.user.email,
        })):
            with self.subTest(field=field):
                original = self.charges[self.old.reference]
                self.charges[self.old.reference] = {**original, field: value}
                with self.assertRaises(PaystackError):
                    self.start()
                self.charges[self.old.reference] = original
        self.assertFalse(StudyPlanChange.objects.exists())
        self.initialize.assert_not_called()

    def test_current_renewal_not_initial_purchase_gets_the_credit(self):
        initial_paid = timezone.now() - timedelta(days=40)
        self.charges[self.old.reference]["paid_at"] = initial_paid.isoformat()
        StudyPayment.objects.filter(pk=self.old.pk).update(created_at=initial_paid - timedelta(minutes=1))
        start = timezone.now() - timedelta(days=2)
        renewal = StudyPayment.objects.create(
            user=self.user, mode="live", source="renewal", tier="grow", plan="monthly", status="succeeded",
            expected_amount_cents=3500, currency="ZAR", checkout_email=self.user.email,
            paystack_plan_code="PLN_growLive", paystack_transaction_id=102, verified_at=start,
            period_start=start, period_end=_one_month_after(start),
            paystack_subscription_code="SUB_old", paystack_invoice_code="INV_current",
        )
        self.charges[renewal.reference] = self.charge(renewal, start, 102)
        StudyMembership.objects.filter(pk=self.member.pk).update(paid_until=renewal.period_end)
        self.pay()
        self.settle()
        refund = self.process_refund()
        self.assertEqual((refund.payment_id, refund.amount_cents, refund.status), (renewal.pk, 3500, "processing"))
        self.assertEqual(self.create_refund.call_args.args[:2], (102, 3500))

    def test_unverified_paid_through_date_does_not_authorise_upgrade(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(paid_until=self.member.paid_until + timedelta(days=1))
        with self.assertRaises(CheckoutNotAllowed):
            self.start()
        self.initialize.assert_not_called()

    def test_payment_already_linked_to_another_subscription_is_not_reassigned(self):
        StudyPayment.objects.filter(pk=self.old.pk).update(paystack_subscription_code="SUB_unrelated")
        with self.assertRaises(PaystackError):
            self.start()
        self.initialize.assert_not_called()
        self.assertEqual(StudyPayment.objects.get(pk=self.old.pk).paystack_subscription_code, "SUB_unrelated")

    def test_verified_payment_starts_fresh_bloom_month_exactly_once(self):
        payment = self.pay()
        self.member.refresh_from_db()
        self.assertEqual((self.member.tier, self.member.status, self.member.paid_until),
                         ("bloom", "active", payment.period_end))
        self.assertEqual(payment.period_end, _one_month_after(payment.period_start))
        self.assertIsNone(self.member.paystack_subscription_code)
        self.assertEqual(StudyPlanChange.objects.get().state, "settling")
        self.disable.assert_not_called()
        self.verify.reset_mock()
        verify_live_checkout(user=self.user, reference=payment.reference)
        self.assertEqual(StudyMembership.objects.get(user=self.user).paid_until, payment.period_end)
        self.verify.assert_not_called()

    def test_mismatched_upgrade_charge_never_activates_bloom(self):
        payment = self.start()
        canonical = self.charge(payment, timezone.now(), 202)
        for field, value in (("domain", "test"), ("amount", 3500), ("currency", "USD"), ("plan", "PLN_other")):
            with self.subTest(field=field):
                self.charges[payment.reference] = {**canonical, field: value}
                with self.assertRaises(PaystackError):
                    verify_live_checkout(user=self.user, reference=payment.reference)
                self.assert_grow_unchanged()
        self.disable.assert_not_called()
        self.assertFalse(StudyRefund.objects.exists())

    def test_settlement_stops_only_old_subscription_and_queues_full_credit_once(self):
        self.pay()
        change = self.settle()
        self.assertEqual((change.state, change.last_result), ("applied", "upgrade_credit_queued"))
        self.disable.assert_called_once_with("SUB_old", "fake-cancel-token")
        self.assertEqual(self.subscriptions["SUB_new"]["status"], "active")
        self.assertEqual(StudyRefund.objects.get().amount_cents, 3500)
        self.create_refund.assert_not_called()
        self.settle()
        self.assertEqual(StudyRefund.objects.count(), 1)
        self.assertEqual(self.disable.call_count, 1)

    def test_full_credit_after_day_seven_keeps_new_bloom_subscription_active(self):
        payment = self.pay()
        self.settle()
        StudyMembership.objects.filter(pk=self.member.pk).update(paystack_subscription_code="SUB_new")
        refund = self.process_refund()
        self.assertEqual((refund.reason, refund.payment_id, refund.status), ("upgrade", self.old.pk, "processing"))
        self.assertEqual(self.create_refund.call_args.args[:2], (101, 3500))
        self.refunds[refund.paystack_refund_id]["status"] = "processed"
        self.assertEqual(self.process_refund(refund).status, "completed")
        self.old.refresh_from_db()
        self.member.refresh_from_db()
        self.assertEqual(self.old.status, "reversed")
        self.assertEqual((self.member.tier, self.member.status, self.member.paid_until, self.member.paystack_subscription_code),
                         ("bloom", "active", payment.period_end, "SUB_new"))
        self.assertEqual(get_study_tier(self.user), "bloom")
        self.disable.assert_called_once_with("SUB_old", "fake-cancel-token")

    def test_upgrade_paid_after_old_period_ended_does_not_refund_old_month(self):
        payment = self.start()
        paid = self.member.paid_until + timedelta(seconds=1)
        with patch("accounts.upgrade_service.timezone.now", return_value=paid):
            self.pay(payment, paid_at=paid)
            change = self.settle()
        self.assertEqual((change.state, change.last_result), ("applied", "previous_period_ended"))
        self.assertFalse(StudyRefund.objects.exists())
        self.disable.assert_called_once()

    def test_cancellation_timeout_after_acceptance_is_confirmed_by_get(self):
        self.pay()
        def timeout_after_acceptance(code, token):
            self.disable_subscription(code, token)
            raise PaystackError("fake timeout")
        self.disable.side_effect = timeout_after_acceptance
        self.assertEqual(self.settle().state, "applied")
        self.assertEqual(StudyRefund.objects.count(), 1)
        self.disable.assert_called_once()

    def test_unconfirmed_old_cancellation_retries_without_refund_post(self):
        self.pay()
        self.disable.side_effect = PaystackError("fake timeout before acceptance")
        change = self.settle()
        self.assertEqual((change.state, change.last_result), ("settling", "upgrade_provider_confirmation_pending"))
        self.assertGreater(change.next_attempt_at, timezone.now())
        self.assertFalse(StudyRefund.objects.exists())
        self.create_refund.assert_not_called()
        self.disable.side_effect = self.disable_subscription
        self.assertEqual(self.settle().state, "applied")

    def test_unconfirmed_old_cancellation_is_flagged_after_a_day(self):
        self.pay()
        StudyPayment.objects.filter(tier="bloom").update(verified_at=timezone.now() - timedelta(hours=25))
        self.disable.side_effect = PaystackError("fake timeout")
        change = self.settle()
        self.assertEqual((change.state, change.last_result), ("attention", "upgrade_settlement_needs_attention"))
        self.assertFalse(StudyRefund.objects.exists())
        self.create_refund.assert_not_called()

    def test_old_subscription_owner_mismatch_requires_attention_without_cancellation(self):
        self.pay()
        self.subscriptions["SUB_old"]["customer"]["customer_code"] = "CUS_other"
        change = self.settle()
        self.assertEqual((change.state, change.last_result), ("attention", "previous_subscription_owner_mismatch"))
        self.disable.assert_not_called()
        self.assertFalse(StudyRefund.objects.exists())

    def test_old_subscription_linked_as_current_elsewhere_cannot_be_cancelled(self):
        self.pay()
        other = get_user_model().objects.create_user(username="another-owner")
        StudyMembership.objects.create(user=other, tier="grow", plan="monthly", paystack_subscription_code="SUB_old")
        self.assertEqual(self.settle().last_result, "previous_subscription_is_current")
        self.disable.assert_not_called()
        self.assertFalse(StudyRefund.objects.exists())

    def test_pending_guarantee_blocks_new_upgrade_checkout(self):
        request_first_payment_refund(self.user)
        with self.assertRaises(CheckoutNotAllowed):
            self.start()
        self.initialize.assert_not_called()

    def test_guarantee_requested_during_checkout_returns_new_charge_without_overwriting_grow(self):
        payment = self.start()
        request_first_payment_refund(self.user)
        self.pay(payment)
        self.assert_grow_unchanged()
        self.assertEqual(StudyPlanChange.objects.get().state, "cancelled")
        refund = StudyRefund.objects.get(reason="discarded_checkout")
        self.assertEqual((refund.payment_id, refund.amount_cents), (payment.pk, 9000))
        self.assertFalse(StudyRefund.objects.filter(reason="upgrade").exists())

    def test_signed_receipt_recovers_paid_upgrade_for_deactivated_owner(self):
        payment = self.start()
        self.charges[payment.reference] = self.charge(payment, timezone.now(), 202)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(PaymentNotFound):
            verify_live_checkout(user=self.user, reference=payment.reference)
        receipt = PaystackWebhookReceipt.objects.create(
            mode="live", event_type="charge.success", payload_sha256="a" * 64,
            snapshot={"schema_version": 1, "domain": "live", "transaction_reference": payment.reference},
        )
        self.assertEqual(process_live_payment_receipt(receipt.pk).processing_status, "processed")
        self.assert_grow_unchanged()
        self.assertEqual(StudyRefund.objects.get().amount_cents, 9000)
        self.assertEqual(StudyPlanChange.objects.get().state, "cancelled")

    def test_accepted_upgrade_credit_survives_account_deactivation(self):
        self.pay()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.settle()
        self.assertEqual(self.process_refund().status, "processing")
        self.assertEqual(self.create_refund.call_args.args[:2], (101, 3500))

    def test_completed_guarantee_before_upgrade_payment_does_not_refund_grow_twice(self):
        payment = self.start()
        StudyRefund.objects.create(user=self.user, payment=self.old, reason="first_payment", mode="live",
                                   amount_cents=3500, status="completed")
        StudyPayment.objects.filter(pk=self.old.pk).update(status="reversed")
        self.pay(payment)
        change = self.settle()
        self.assertEqual((change.state, change.last_result), ("applied", "previous_payment_already_refunded"))
        self.assertEqual(get_study_tier(self.user), "bloom")
        self.assertFalse(StudyRefund.objects.filter(reason="upgrade").exists())
        self.create_refund.assert_not_called()

    def test_denied_guarantee_does_not_consume_upgrade_credit(self):
        StudyRefund.objects.create(user=self.user, payment=self.old, reason="first_payment", mode="live",
                                   amount_cents=3500, status="ineligible")
        self.pay()
        self.settle()
        self.assertEqual(self.process_refund().status, "processing")
        self.assertEqual(StudyRefund.objects.count(), 2)

    def test_ambiguous_refund_post_is_never_automatically_repeated(self):
        self.pay()
        self.settle()
        self.create_refund.side_effect = PaystackError("fake refund submission timeout")
        refund = self.process_refund()
        self.assertEqual(refund.status, "submitting")
        self.process_refund(refund)
        self.create_refund.assert_called_once()
        self.assertEqual(StudyRefund.objects.get().last_result, "waiting_for_provider_refund")

    def test_refund_timeout_after_provider_acceptance_is_reconciled_without_second_post(self):
        self.pay()
        self.settle()
        def timeout_after_refund(*args, **kwargs):
            self.submit_refund(*args, **kwargs)
            raise PaystackError("fake timeout")
        self.create_refund.side_effect = timeout_after_refund
        refund = self.process_refund()
        self.assertEqual(refund.status, "submitting")
        self.assertEqual(self.process_refund(refund).status, "processing")
        self.create_refund.assert_called_once()

    def test_pausing_new_sales_and_refunds_does_not_strand_accepted_upgrade(self):
        self.pay()
        with override_settings(PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False,
                               PAYSTACK_LIVE_CHECKOUT_ENABLED=False, PAYSTACK_LIVE_REFUNDS_ENABLED=False):
            self.assertEqual(process_upgrade_batch()[0][1], "applied")
            self.assertEqual(self.process_refund().status, "processing")

    def test_first_guarantee_button_cannot_cancel_new_bloom_for_old_grow_payment(self):
        self.pay()
        with self.assertRaises(RefundNotAllowed):
            request_first_payment_refund(self.user)
        request = RequestFactory().get("/my-plan/", secure=True, HTTP_HOST="studigarden.com")
        request.user = self.user
        self.assertFalse(refund_page_context(request)["can_request_refund"])
        self.assertFalse(StudyRefund.objects.exists())

    def test_one_worker_pass_verifies_upgrade_stops_old_and_submits_its_credit(self):
        payment = self.start()
        self.charges[payment.reference] = self.charge(payment, timezone.now(), 202)
        PaystackWebhookReceipt.objects.create(
            mode="live", event_type="charge.success", payload_sha256="b" * 64,
            snapshot={"schema_version": 1, "domain": "live", "transaction_reference": payment.reference},
        )
        output = io.StringIO()
        call_command("process_paystack_live_events", once=True, stdout=output)
        self.assertEqual(get_study_tier(self.user), "bloom")
        self.assertEqual(StudyPlanChange.objects.get().state, "applied")
        self.assertEqual(StudyRefund.objects.get().status, "processing")
        self.assertNotIn("fake-cancel-token", output.getvalue())
        self.assertNotIn(self.user.email, output.getvalue())

    def test_replacement_late_payment_uses_existing_discarded_checkout_recovery(self):
        old_upgrade = self.start()
        chosen = prepare_live_upgrade(user=self.user, replace_reference=old_upgrade.reference)
        self.assertNotEqual(old_upgrade.pk, chosen.pk)
        self.pay(old_upgrade)
        self.assert_grow_unchanged()
        self.assertEqual(StudyPlanChange.objects.get().payment_id, chosen.pk)
        self.assertEqual(StudyRefund.objects.get().payment_id, old_upgrade.pk)

    def test_processing_checkout_cannot_be_replaced_and_charged_again(self):
        payment = self.start()
        self.charges[payment.reference] = {
            **self.verify_charge(payment.reference), "status": "processing",
        }
        with self.assertRaises(CheckoutNotAllowed):
            prepare_live_upgrade(user=self.user, replace_reference=payment.reference)
        self.assertEqual(StudyPayment.objects.count(), 2)
        self.assertIsNone(StudyPayment.objects.get(pk=payment.pk).discarded_at)

    def test_ordinary_paid_checkout_remains_blocked_until_switch_controls_are_connected(self):
        with self.assertRaises(CheckoutNotAllowed):
            initialize_live_checkout(user=self.user, tier="bloom")
        self.initialize.assert_not_called()

    def test_wrong_new_transaction_id_cannot_be_reused_for_upgrade(self):
        payment = self.start()
        self.charges[payment.reference] = self.charge(payment, timezone.now(), 101)
        with self.assertRaises(PaystackError):
            verify_live_checkout(user=self.user, reference=payment.reference)
        self.assert_grow_unchanged()

    def test_tampered_old_payment_scope_does_not_trigger_cancellation_or_refund(self):
        self.pay()
        other = get_user_model().objects.create_user(username="unrelated-payment")
        StudyPayment.objects.filter(pk=self.old.pk).update(user=other)
        self.assertEqual(self.settle().last_result, "upgrade_scope_changed")
        self.disable.assert_not_called()
        self.create_refund.assert_not_called()

    def test_changed_verified_upgrade_period_is_not_refunded_on_untrusted_dates(self):
        payment = self.pay()
        StudyPayment.objects.filter(pk=payment.pk).update(period_end=payment.period_end + timedelta(days=1))
        self.assertEqual(self.settle().last_result, "funded_period_mismatch")
        self.create_refund.assert_not_called()
        self.assertFalse(StudyRefund.objects.exists())

    def test_disabling_plan_changes_prevents_any_new_upgrade_checkout(self):
        with override_settings(PAYSTACK_LIVE_PLAN_CHANGES_ENABLED=False), self.assertRaises(CheckoutNotAllowed):
            self.start()
        self.initialize.assert_not_called()
        self.assertFalse(StudyPlanChange.objects.exists())

    def test_stopped_grow_can_upgrade_without_reenabling_old_subscription(self):
        StudyMembership.objects.filter(pk=self.member.pk).update(status="non_renewing")
        self.subscriptions["SUB_old"]["status"] = "non-renewing"
        self.pay()
        self.assertEqual(self.settle().state, "applied")
        self.disable.assert_not_called()
        self.assertEqual(self.process_refund().status, "processing")

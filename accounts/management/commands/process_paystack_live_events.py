"""Durable live billing worker; also processes user-authorised refund requests."""

import signal
import threading

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections
from django.db.models import Q
from django.utils import timezone

from accounts.models import PaystackWebhookReceipt
from accounts.payment_webhooks import PAYMENT_EVENTS, process_live_payment_receipt
from accounts.paystack_client import live_billing_enabled
from accounts.refund_service import process_refund_batch
from accounts.subscription_webhooks import SUBSCRIPTION_EVENTS, State, _finish, process_live_subscription_receipt
from accounts.upgrade_service import process_upgrade_batch
from accounts.downgrade_service import process_downgrade_batch


def process_batch(limit=10):
    if not live_billing_enabled():
        raise CommandError("Live billing is disabled or incorrectly configured. No events processed.")
    receipts = list(PaystackWebhookReceipt.objects.filter(
        mode="live", event_type__in=(*PAYMENT_EVENTS, *SUBSCRIPTION_EVENTS),
        processing_status__in=("received", "retry"),
    ).filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()))
        .order_by("received_at", "pk").values_list("pk", "event_type")[:limit])
    outcomes = []
    for receipt_id, event_type in receipts:
        process = process_live_payment_receipt if event_type in PAYMENT_EVENTS else process_live_subscription_receipt
        # Processors deliberately return only internal, non-sensitive outcomes.
        try:
            receipt = process(receipt_id)
        except DatabaseError:
            # Losing database durability is a process failure, not an ack.
            raise
        except Exception:
            # An unexpected provider shape or a single poison event must not
            # repeatedly restart the website or prevent other receipts running.
            # Keep it visible for review without logging provider data/secrets.
            receipt = _finish(receipt_id, State.RETRY, "processor_error")
        outcomes.append((receipt.pk, receipt.processing_status, receipt.last_result))
    return outcomes


class Command(BaseCommand):
    help = "Process signed live Paystack receipts. --watch waits for new work; --once runs one batch."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--watch", action="store_true")
        group.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        if not live_billing_enabled():
            raise CommandError("Live billing is disabled or incorrectly configured. No worker started.")
        stopped = threading.Event()
        previous = {}
        if options["watch"]:
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, lambda signum, frame: stopped.set())
        self.stdout.write("Live Paystack inbox worker ready. Only verified notifications update access.")
        try:
            while not stopped.is_set():
                close_old_connections()
                for receipt_id, state, result in process_batch():
                    self.stdout.write(f"Payment receipt {receipt_id}: {state} ({result})")
                for change_id, state, result in process_upgrade_batch():
                    self.stdout.write(f"Plan change {change_id}: {state} ({result})")
                for change_id, state, result in process_downgrade_batch():
                    self.stdout.write(f"Plan change {change_id}: {state} ({result})")
                for refund_id, state, result in process_refund_batch():
                    self.stdout.write(f"Refund request {refund_id}: {state} ({result})")
                close_old_connections()
                if options["once"]:
                    break
                stopped.wait(30)
        finally:
            close_old_connections()
            for sig, handler in previous.items():
                signal.signal(sig, handler)

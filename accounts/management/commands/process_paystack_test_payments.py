"""One explicit, bounded batch against the disposable local database only."""

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.db.models import Q
from django.utils import timezone

from accounts.management.commands.create_paystack_test_user import _require_disposable_preview
from accounts.models import PaystackWebhookReceipt
from accounts.payment_webhooks import PAYMENT_EVENTS, process_test_payment_receipt
from accounts.paystack_client import PaystackError


class Command(BaseCommand):
    help = "Reconcile a local batch of signed TEST payment notifications using Paystack GETs only."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25)

    def handle(self, *args, **options):
        _require_disposable_preview()
        limit = options["limit"]
        if not 1 <= limit <= 100:
            raise CommandError("Choose a batch limit between 1 and 100.")
        self.stdout.write("Local TEST payment reconciliation. No charges, refunds or provider changes will be made.")
        try:
            ids = list(PaystackWebhookReceipt.objects.filter(
                mode="test", event_type__in=PAYMENT_EVENTS, processing_status__in=["received", "retry"],
            ).filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()))
                .order_by("received_at", "pk").values_list("pk", flat=True)[:limit])
            for receipt_id in ids:
                receipt = process_test_payment_receipt(receipt_id)
                self.stdout.write(f"Receipt {receipt.pk}: {receipt.processing_status} ({receipt.last_result})")
        except (DatabaseError, PaystackError):
            raise CommandError("The local batch could not finish safely. Try again later; no provider details were printed.") from None
        if not ids:
            self.stdout.write("No due test payment notifications.")

"""One bounded local batch; production scheduling is deliberately not enabled."""

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.db.models import Q
from django.utils import timezone

from accounts.management.commands.create_paystack_test_user import _require_disposable_preview
from accounts.models import PaystackWebhookReceipt, StudyPayment
from accounts.paystack_client import PaystackError
from accounts.subscription_webhooks import SUBSCRIPTION_EVENTS, process_test_subscription_receipt


class Command(BaseCommand):
    help = "Process one local batch of signed test subscription notifications; no Paystack writes."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25)

    def handle(self, *args, **options):
        _require_disposable_preview()
        limit = options["limit"]
        if not 1 <= limit <= 100:
            raise CommandError("Choose a batch limit between 1 and 100.")
        ids = list(PaystackWebhookReceipt.objects.filter(
            mode=StudyPayment.Mode.TEST, event_type__in=SUBSCRIPTION_EVENTS,
            processing_status__in=["received", "retry"],
        ).filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()))
            .order_by("received_at", "pk").values_list("pk", flat=True)[:limit])
        self.stdout.write("Local test subscription batch. Paystack will only be read; paid-through dates will not be extended.")
        if not ids:
            self.stdout.write("No due test subscription notifications. Payment/invoice events are left queued for the next step.")
            return
        for receipt_id in ids:
            try:
                receipt = process_test_subscription_receipt(receipt_id)
            except (DatabaseError, PaystackError):
                raise CommandError("The batch could not finish safely. No provider error details were printed; try again later.") from None
            self.stdout.write(f"Receipt {receipt.pk}: {receipt.processing_status} ({receipt.last_result})")

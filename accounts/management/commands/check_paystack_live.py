"""Read-only production configuration check; never creates a checkout."""

from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import StudyTier
from accounts.paystack_checkout import _validate_plan
from accounts.paystack_client import PaystackError, PaystackLiveClient, live_billing_enabled, live_checkout_enabled
from accounts.plans import STUDY_PLANS


class Command(BaseCommand):
    help = "Validate LIVE monthly plans using GET only. No charges or account changes."

    def handle(self, *args, **options):
        self.stdout.write("Read-only live-plan check. No payments or account changes will be made.")
        if not live_billing_enabled():
            raise CommandError("Live billing requires DEBUG=False, its enable flag, and a live secret key.")
        client = PaystackLiveClient()
        codes = settings.PAYSTACK_LIVE_PLAN_CODES
        if not codes.get("grow") or not codes.get("bloom") or codes["grow"] == codes["bloom"]:
            raise CommandError("Set separate LIVE Grow and Bloom plan codes first.")
        for tier in (StudyTier.GROW, StudyTier.BLOOM):
            try:
                payment = SimpleNamespace(
                    mode="live", paystack_plan_code=codes[tier],
                    expected_amount_cents=STUDY_PLANS[tier].monthly_amount_cents, currency="ZAR",
                )
                _validate_plan(client.fetch_plan(codes[tier]), payment)
            except PaystackError:
                raise CommandError(f"{tier}: live mode, plan, currency, amount or monthly interval did not validate.") from None
            self.stdout.write(f"{tier}: verified LIVE monthly ZAR plan (R{payment.expected_amount_cents // 100}).")
        self.stdout.write("New checkout: " + ("ENABLED" if live_checkout_enabled() else "disabled"))

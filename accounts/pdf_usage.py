"""Account-wide PDF allowances that reset each local calendar month."""

from contextlib import contextmanager
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .access import get_study_tier
from .models import StudyMonthlyUsage, StudyTier
from .plans import STUDY_PLANS


class PDFLimitExceeded(ValueError):
    pass


def current_usage_month():
    return timezone.localdate().replace(day=1)


def get_pdf_usage(user):
    period = current_usage_month()
    plan = STUDY_PLANS.get(get_study_tier(user), STUDY_PLANS[StudyTier.FREE])
    unlimited = bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.is_superuser
    )
    usage = StudyMonthlyUsage.objects.filter(user_id=user.pk, period_start=period).first()
    exports = usage.pdf_exports if usage else 0
    pages = usage.summary_pages if usage else 0
    return {
        "period_start": period,
        "resets_on": (period.replace(day=28) + timedelta(days=4)).replace(day=1),
        "pdf_exports": exports,
        "summary_pages": pages,
        "exports_remaining": (
            None
            if unlimited or plan.monthly_pdf_exports is None
            else max(0, plan.monthly_pdf_exports - exports)
        ),
        "pages_remaining": (
            None
            if unlimited or plan.monthly_summary_pages is None
            else max(0, plan.monthly_summary_pages - pages)
        ),
    }


class PDFAllowance:
    def __init__(self, record, plan, *, unlimited=False):
        self.record = record
        self.plan = plan
        self.unlimited = unlimited

    def add_export(self):
        limit = self.plan.monthly_pdf_exports
        if not self.unlimited and limit is not None and self.record.pdf_exports >= limit:
            raise PDFLimitExceeded(
                f"You have used your {limit} PDF exports for this month. "
                "Your allowance resets next month, or you can upgrade to Bloom."
            )
        self.record.pdf_exports += 1

    def check_summary_pages(self, number):
        if number < 1:
            raise ValueError("Choose at least one PDF page.")
        limit = self.plan.monthly_summary_pages
        if not self.unlimited and limit is not None and self.record.summary_pages + number > limit:
            remaining = max(0, limit - self.record.summary_pages)
            raise PDFLimitExceeded(
                f"You have {remaining} Auto Summarize pages remaining this month. "
                "Choose a smaller page range, wait until next month, or upgrade to Bloom."
            )

    def add_summary_pages(self, number):
        self.check_summary_pages(number)
        self.record.summary_pages += number


@contextmanager
def monthly_pdf_allowance(user):
    # Serialize PDF operations and subject creation for this user on PostgreSQL.
    # An exception rolls back the counters, so failed work does not use an allowance.
    with transaction.atomic():
        account = get_user_model().objects.select_for_update().get(pk=user.pk)
        tier = get_study_tier(account)
        unlimited = bool(account.is_active and account.is_superuser)
        if not unlimited and tier not in {StudyTier.GROW, StudyTier.BLOOM}:
            raise PDFLimitExceeded("PDF tools are included in Grow and Bloom.")
        record, _ = StudyMonthlyUsage.objects.get_or_create(
            user=account, period_start=current_usage_month(),
        )
        plan = STUDY_PLANS.get(tier, STUDY_PLANS[StudyTier.FREE])
        yield PDFAllowance(record, plan, unlimited=unlimited)
        record.save(update_fields=["pdf_exports", "summary_pages"])

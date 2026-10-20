"""Shared public plan names and prices, in South African rand."""

from dataclasses import dataclass
from decimal import Decimal

from .models import StudyTier


@dataclass(frozen=True)
class StudyPlan:
    tier: StudyTier
    monthly_amount_cents: int
    subject_limit: int | None
    learning_items_per_subject: int | None
    monthly_pdf_exports: int | None
    monthly_summary_pages: int | None

    @property
    def name(self):
        return self.tier.label

    @property
    def monthly_price(self):
        return Decimal(self.monthly_amount_cents) / 100

    @property
    def features(self):
        features = [
            f"Up to {self.subject_limit} subjects" if self.subject_limit else "Unlimited subjects",
            f"{self.learning_items_per_subject} learning items per subject"
            if self.learning_items_per_subject else "Unlimited learning items",
            "Study planning, reviews, exams and progress tracking",
        ]
        if self.tier == StudyTier.FREE:
            features.append("PDF exports and Auto Summarize are not included")
        else:
            features.extend([
                f"{self.monthly_pdf_exports} PDF exports per month"
                if self.monthly_pdf_exports is not None else "Unlimited PDF exports",
                f"Auto Summarize up to {self.monthly_summary_pages} PDF pages per month"
                if self.monthly_summary_pages is not None else "Auto Summarize with no monthly page limit",
            ])
        return tuple(features)


STUDY_PLANS = {
    StudyTier.FREE: StudyPlan(StudyTier.FREE, 0, 2, 100, 0, 0),
    StudyTier.GROW: StudyPlan(StudyTier.GROW, 3500, 7, None, 2, 5),
    StudyTier.BLOOM: StudyPlan(StudyTier.BLOOM, 9000, None, None, None, None),
}

PAID_STUDY_PLANS = tuple(
    plan for tier, plan in STUDY_PLANS.items() if tier != StudyTier.FREE
)

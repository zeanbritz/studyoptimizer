"""Explicit payment proof for checkouts and provider-scheduled lower plans."""

from datetime import timedelta

from .models import StudyPayment, StudyPlanChange


def membership_payment(member, plan_code=None):
    if member.payment_mode == "live" and member.paystack_subscription_code:
        change = StudyPlanChange.objects.filter(
            user_id=member.user_id, kind="downgrade", from_tier="bloom", to_tier=member.tier,
            to_subscription_code=member.paystack_subscription_code,
            state__in=("applied", "cancelled", "settling"), payment__isnull=False,
        ).select_related("payment").first()
        if change:
            payment = change.payment
            if (payment.user_id == member.user_id and payment.mode == "live"
                    and payment.tier == change.to_tier and payment.plan == "monthly" and payment.source == "renewal"
                    and payment.status == "succeeded" and payment.verified_at and payment.paystack_transaction_id
                    and not payment.discarded_at and payment.paystack_subscription_code == change.to_subscription_code
                    and payment.paystack_plan_code == change.to_plan_code
                    and payment.expected_amount_cents == change.monthly_amount_cents
                    and payment.currency == change.currency == "ZAR" and change.old_stopped_at
                    and payment.period_start and payment.period_start >= change.effective_at - timedelta(seconds=1)
                    and (plan_code is None or payment.paystack_plan_code == plan_code)):
                return payment
            # An explicit subscription binding must not fall back to an older,
            # unrelated same-tier checkout if its actual payment proof is broken.
            return None
    payments = StudyPayment.objects.filter(
        user_id=member.user_id, mode=member.payment_mode, tier=member.tier, plan="monthly", source="checkout",
        status="succeeded", verified_at__isnull=False, discarded_at__isnull=True,
    ).exclude(paystack_plan_code="")
    if plan_code is not None:
        payments = payments.filter(paystack_plan_code=plan_code)
    return payments.first()

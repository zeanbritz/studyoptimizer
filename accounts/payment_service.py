from allauth.account.models import EmailAddress
from django.conf import settings

from .access import has_permanent_free_access
from .models import StudyMembership, StudyPayment, StudyTier
from .plans import STUDY_PLANS


class CheckoutNotAllowed(ValueError):
    """The account or selected plan cannot start checkout."""


def create_test_checkout_attempt(*, user, tier, plan=StudyMembership.Plan.MONTHLY):
    return create_checkout_attempt(user=user, tier=tier, plan=plan, mode="test")


def create_checkout_attempt(*, user, tier, plan=StudyMembership.Plan.MONTHLY, mode="test"):
    """
    Record a mode-specific checkout attempt without contacting Paystack.

    The price, Paystack plan code, currency and mode are selected here. This
    only records an attempt; it never charges a card or grants membership.
    """
    if (
        user is None
        or not user.is_authenticated
        or not user.is_active
        or user.pk is None
    ):
        raise CheckoutNotAllowed("An active account is required.")

    if has_permanent_free_access(user):
        raise CheckoutNotAllowed("This account already has free access.")

    if not user.email or not EmailAddress.objects.filter(
        user=user,
        email__iexact=user.email,
        verified=True,
    ).exists():
        raise CheckoutNotAllowed("A verified email address is required.")

    if not isinstance(tier, str) or tier not in {StudyTier.GROW, StudyTier.BLOOM}:
        raise CheckoutNotAllowed("Choose Grow or Bloom for paid checkout.")

    if plan != StudyMembership.Plan.MONTHLY:
        raise CheckoutNotAllowed("Only monthly billing is currently offered.")

    if mode not in {"test", "live"}:
        raise CheckoutNotAllowed("Unsupported payment mode.")
    codes = settings.PAYSTACK_TEST_PLAN_CODES if mode == "test" else settings.PAYSTACK_LIVE_PLAN_CODES
    plan_code = codes.get(tier, "").strip()
    if not plan_code.startswith("PLN_") or len(plan_code) <= 4:
        raise CheckoutNotAllowed("The selected plan is not configured.")

    return StudyPayment.objects.create(
        user=user,
        tier=tier,
        plan=plan,
        paystack_plan_code=plan_code,
        mode=mode,
        source=StudyPayment.Source.CHECKOUT,
        expected_amount_cents=STUDY_PLANS[tier].monthly_amount_cents,
        currency="ZAR",
        checkout_email=user.email,
    )

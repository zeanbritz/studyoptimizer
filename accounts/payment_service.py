from allauth.account.models import EmailAddress

from .access import has_permanent_free_access
from .models import StudyMembership, StudyPayment


PLAN_AMOUNTS_CENTS = {
    StudyMembership.Plan.MONTHLY: 9900,
    StudyMembership.Plan.YEARLY: 99900,
}


class CheckoutNotAllowed(ValueError):
    """The account or selected plan cannot start checkout."""


def create_test_checkout_attempt(*, user, plan):
    """
    Record a test-mode checkout attempt without contacting Paystack.

    The amount and mode are selected here, never supplied by the browser.
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

    try:
        amount_cents = PLAN_AMOUNTS_CENTS[plan]
    except (KeyError, TypeError):
        raise CheckoutNotAllowed("Unknown study plan.") from None

    return StudyPayment.objects.create(
        user=user,
        plan=plan,
        mode=StudyPayment.Mode.TEST,
        source=StudyPayment.Source.CHECKOUT,
        expected_amount_cents=amount_cents,
        currency="ZAR",
    )
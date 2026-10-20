from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .access import get_study_tier
from .entitlements import FREE_LEARNING_ITEM_LIMIT, FREE_SUBJECT_LIMIT
from .models import BetaInvite, StudyMembership, StudyTier
from .plans import STUDY_PLANS
from .pdf_usage import get_pdf_usage


@login_required
def my_plan(request):
    user = request.user

    is_beta_member = (
        user.beta_lifetime_access
        or BetaInvite.objects.filter(claimed_by_id=user.pk).exists()
    )

    membership = StudyMembership.objects.filter(user=user).first()
    tier = get_study_tier(user)

    return render(
        request,
        "accounts/my_plan.html",
        {
            "is_beta_member": is_beta_member,
            "membership": membership,
            "has_paid_access": tier in {StudyTier.GROW, StudyTier.BLOOM},
            "current_plan": STUDY_PLANS.get(tier, STUDY_PLANS[StudyTier.FREE]),
            "pdf_usage": get_pdf_usage(user),
            "free_subject_limit": FREE_SUBJECT_LIMIT,
            "free_learning_item_limit": FREE_LEARNING_ITEM_LIMIT,
        },
    )

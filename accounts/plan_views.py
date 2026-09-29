from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import BetaInvite, StudyMembership


@login_required
def my_plan(request):
    user = request.user

    is_beta_member = (
        user.beta_lifetime_access
        or BetaInvite.objects.filter(claimed_by_id=user.pk).exists()
    )

    membership = StudyMembership.objects.filter(user=user).first()

    return render(
        request,
        "accounts/my_plan.html",
        {
            "is_beta_member": is_beta_member,
            "membership": membership,
        },
    )
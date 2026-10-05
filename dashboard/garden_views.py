from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from learning.models import Subject


@login_required
@require_GET
def beta_garden(request):
    """Show the private subject garden without changing study data."""
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied

    subjects = list(
        Subject.objects.filter(user=request.user).order_by("created", "pk")
    )
    subject_indexes = {
        entry.get("database_id"): index
        for index, entry in enumerate(request.session.get("onboarding_subjects", []))
        if isinstance(entry, dict)
    }
    garden_subjects = [
        {
            "subject": subject,
            "detail_url": reverse(
                "subject_detail", args=[subject_indexes[subject.pk]]
            ) if subject.pk in subject_indexes else reverse("goals"),
        }
        for subject in subjects
    ]
    return render(
        request,
        "dashboard/beta_garden.html",
        {"garden_subjects": garden_subjects},
    )

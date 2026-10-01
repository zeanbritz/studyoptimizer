from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from learning.models import Subject


@login_required
@require_GET
def beta_garden(request):
    """A read-only preview of a possible study garden."""
    subjects = Subject.objects.filter(user=request.user).order_by("created", "pk")
    return render(request, "dashboard/beta_garden.html", {"garden_subjects": subjects})

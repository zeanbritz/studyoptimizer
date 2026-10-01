from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET


@login_required
@require_GET
def beta_garden(request):
    """A read-only preview of a possible study garden."""
    return render(request, "dashboard/beta_garden.html")

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_GET
@login_required
@require_GET
def beta_garden(request):
    """Keep old bookmarks useful; the standalone garden has been retired."""
    return redirect(reverse("dashboard") + "?view=garden")

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .account_deletion import account_deletion_blocker, erase_student_account


@never_cache
@login_required
@require_POST
def delete_account(request):
    if request.POST.get("confirm_delete") != "yes":
        messages.error(request, "Confirm that you understand your study data will be permanently deleted.")
        return redirect("my_plan")

    blocker = account_deletion_blocker(request.user)
    if blocker:
        messages.error(request, blocker)
        return redirect("my_plan")

    try:
        erase_student_account(request.user)
    except ValueError as error:
        messages.error(request, str(error))
        return redirect("my_plan")

    logout(request)
    messages.success(request, "Your StudiGarden account and study data were deleted.")
    return redirect("landing")

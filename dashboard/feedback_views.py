from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import BetaFeedback


class BetaFeedbackForm(forms.ModelForm):
    class Meta:
        model = BetaFeedback
        fields = ("category", "message")

    def clean_message(self):
        message = self.cleaned_data["message"].strip()

        if not message:
            raise forms.ValidationError("Please write a message.")

        return message


@login_required
@require_POST
def submit_beta_feedback(request):
    if not settings.BETA_FEEDBACK_ENABLED:
        raise Http404

    recent_count = BetaFeedback.objects.filter(
        user=request.user,
        created_at__gte=timezone.now() - timedelta(hours=1),
    ).count()

    if recent_count >= 10:
        return JsonResponse(
            {
                "ok": False,
                "error": "You've sent several messages recently. Please try again later.",
            },
            status=429,
        )

    form = BetaFeedbackForm(request.POST)

    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "error": "Choose a type and write a message of up to 2,000 characters.",
            },
            status=400,
        )

    feedback = form.save(commit=False)
    feedback.user = request.user

    page_path = request.POST.get("page_path", "").strip()
    page_path = page_path.split("?", 1)[0].split("#", 1)[0]

    if page_path.startswith("/") and not page_path.startswith("//"):
        feedback.page_path = page_path[:255]

    feedback.save()

    return JsonResponse({"ok": True})
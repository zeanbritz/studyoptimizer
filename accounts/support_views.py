from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import SupportQuery


class SupportQueryForm(forms.ModelForm):
    class Meta:
        model = SupportQuery
        fields = ("category", "message")

    def clean_message(self):
        message = self.cleaned_data["message"].strip()
        if not message:
            raise forms.ValidationError("Please describe what you need help with.")
        return message


def _safe_page_path(raw_path):
    path = raw_path.strip().split("?", 1)[0].split("#", 1)[0]
    if path.startswith("/") and not path.startswith("//"):
        return path[:255]
    return ""


def _reply_to(email):
    try:
        validate_email(email)
    except ValidationError:
        return []
    return [email]


def _send_support_email(query):
    support_email = settings.STUDIGARDEN_SUPPORT_EMAIL.strip()
    if not support_email:
        return False

    submitted_at = timezone.localtime(query.created_at).strftime("%d %B %Y at %H:%M %Z")
    body = "\n".join(
        (
            f"StudiGarden support request #{query.pk}",
            "",
            f"Type: {query.get_category_display()}",
            f"Student: {query.username}",
            f"Registered email: {query.email}",
            f"Submitted: {submitted_at}",
            f"Page: {query.page_path or 'Profile'}",
            "",
            "Student's query:",
            query.message,
            "",
            f"This request is also saved in Django admin as support request #{query.pk}.",
        )
    )
    email = EmailMessage(
        subject=f"StudiGarden support #{query.pk}: {query.get_category_display()}",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[support_email],
        reply_to=_reply_to(query.email),
    )
    try:
        return email.send(fail_silently=False) == 1
    except Exception:
        return False


@login_required
@require_POST
def submit_support_query(request):
    recent_count = SupportQuery.objects.filter(
        user=request.user,
        created_at__gte=timezone.now() - timedelta(hours=1),
    ).count()
    if recent_count >= 5:
        return JsonResponse(
            {
                "ok": False,
                "error": "You've sent several support requests recently. Please try again later.",
            },
            status=429,
        )

    form = SupportQueryForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "error": "Choose a help topic and enter a message of up to 4,000 characters.",
            },
            status=400,
        )

    query = form.save(commit=False)
    query.user = request.user
    query.username = request.user.get_username()
    query.email = request.user.email
    query.page_path = _safe_page_path(request.POST.get("page_path", ""))
    query.save()

    sent = _send_support_email(query)
    query.email_status = (
        SupportQuery.EmailStatus.SENT if sent else SupportQuery.EmailStatus.FAILED
    )
    query.email_attempted_at = timezone.now()
    query.save(update_fields=("email_status", "email_attempted_at", "updated_at"))

    if sent:
        message = f"Your support request was sent. Reference #{query.pk}."
    else:
        message = (
            f"Your support request was saved as #{query.pk}. Email delivery is delayed, "
            "but it is visible to support in the admin log."
        )

    return JsonResponse({"ok": True, "message": message}, status=200 if sent else 202)

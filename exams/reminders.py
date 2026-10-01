from datetime import timedelta

from .models import AssessmentEvent


def due_reminders(user, today):
    """Active events that have reached their reminder date, including overdue ones."""
    events = AssessmentEvent.objects.filter(
        subject__user=user,
        completed_at__isnull=True,
        date__lte=today + timedelta(days=365),
    ).select_related("subject").order_by("date", "pk")
    return [event for event in events if event.reminder_date <= today]

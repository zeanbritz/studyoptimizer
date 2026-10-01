"""Keep the calendar and the legacy subject Exam date in agreement."""

from django.db.models import Min, Q
from django.utils import timezone

from .models import AssessmentEvent


def refresh_subject_exam_dates(subjects):
    """Advance each subject's displayed date to its next calendar exam."""
    subject_ids = [subject.pk for subject in subjects]
    if not subject_ids:
        return

    today = timezone.localdate()
    next_dates = dict(
        AssessmentEvent.objects.filter(
            subject_id__in=subject_ids,
            kind=AssessmentEvent.Kind.EXAM,
            completed_at__isnull=True,
        ).order_by().values("subject_id").annotate(
            next_date=Min("date", filter=Q(date__gte=today)),
        ).values_list("subject_id", "next_date")
    )

    for subject in subjects:
        if subject.pk not in next_dates:
            continue
        next_date = next_dates.get(subject.pk)
        if subject.exam_date != next_date:
            subject.exam_date = next_date
            subject.save(update_fields=["exam_date"])


def sync_subject_next_exam(request, subject):
    """Write the next exam to both the database and the current session."""
    next_date = AssessmentEvent.objects.filter(
        subject=subject,
        kind=AssessmentEvent.Kind.EXAM,
        completed_at__isnull=True,
        date__gte=timezone.localdate(),
    ).order_by("date", "pk").values_list("date", flat=True).first()
    if subject.exam_date != next_date:
        subject.exam_date = next_date
        subject.save(update_fields=["exam_date"])

    entries = request.session.get("onboarding_subjects")
    if not isinstance(entries, list):
        return
    date_text = next_date.isoformat() if next_date else ""
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or str(entry.get("database_id")) != str(subject.pk):
            continue
        if entry.get("exam_date") != date_text:
            entries[index] = {**entry, "exam_date": date_text}
            request.session["onboarding_subjects"] = entries
            request.session.modified = True
        break


def update_exam_from_subject_detail(request, subject, old_date, new_date):
    """Treat the subject's date field as an editor for its next exam."""
    if old_date != new_date:
        current_event = None
        if old_date is not None:
            current_event = AssessmentEvent.objects.filter(
                subject=subject,
                kind=AssessmentEvent.Kind.EXAM,
                date=old_date,
            ).order_by("pk").first()

        if new_date is None:
            if current_event is not None:
                current_event.delete()
        elif current_event is not None:
            current_event.date = new_date
            current_event.save(update_fields=["date"])
        elif not AssessmentEvent.objects.filter(
            subject=subject,
            kind=AssessmentEvent.Kind.EXAM,
            date=new_date,
        ).exists():
            AssessmentEvent.objects.create(
                subject=subject,
                kind=AssessmentEvent.Kind.EXAM,
                date=new_date,
            )

    sync_subject_next_exam(request, subject)

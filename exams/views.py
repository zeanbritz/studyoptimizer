import calendar
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from learning.models import Subject

from .forms import AssessmentEventForm
from .models import AssessmentEvent
from .sync import sync_subject_next_exam


def _date_or_none(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _month_or_none(value):
    try:
        year, month = map(int, value.split("-"))
        return date(year, month, 1)
    except (AttributeError, TypeError, ValueError):
        return None


def _calendar_context(request, selected_date, form, editing=None):
    today = timezone.localdate()
    month_start = selected_date.replace(day=1)
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(
        month_start.year, month_start.month
    )
    events = AssessmentEvent.objects.filter(
        subject__user=request.user,
        date__range=(weeks[0][0], weeks[-1][-1]),
    ).select_related("subject")
    events_by_date = {}
    for event in events:
        events_by_date.setdefault(event.date, []).append(event)

    calendar_weeks = [
        [
            {
                "date": day,
                "in_month": day.month == month_start.month,
                "is_today": day == today,
                "is_selected": day == selected_date,
                "events": events_by_date.get(day, []),
            }
            for day in week
        ]
        for week in weeks
    ]
    previous_month = month_start - timedelta(days=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    return {
        "calendar_weeks": calendar_weeks,
        "month_label": month_start.strftime("%B %Y"),
        "previous_month": previous_month.strftime("%Y-%m"),
        "next_month": next_month.strftime("%Y-%m"),
        "selected_date": selected_date,
        "selected_events": events_by_date.get(selected_date, []),
        "upcoming_events": AssessmentEvent.objects.filter(
            subject__user=request.user,
            date__gte=today,
        ).select_related("subject").order_by("date", "pk")[:5],
        "form": form,
        "editing": editing,
        "has_subjects": Subject.objects.filter(user=request.user).exists(),
    }


@login_required
def calendar_view(request):
    today = timezone.localdate()
    editing = None

    if request.method == "POST":
        event_id = request.POST.get("event_id")
        if event_id:
            editing = get_object_or_404(
                AssessmentEvent,
                pk=event_id,
                subject__user=request.user,
            )

        if request.POST.get("action") == "delete":
            if editing is None:
                return HttpResponseBadRequest("Choose an event to delete.")
            selected_date = editing.date
            old_subject = editing.subject
            was_exam = editing.kind == AssessmentEvent.Kind.EXAM
            editing.delete()
            if was_exam:
                sync_subject_next_exam(request, old_subject)
            return redirect(f"{reverse('exams:calendar')}?date={selected_date.isoformat()}")

        if request.POST.get("action") == "move":
            if editing is None:
                return HttpResponseBadRequest("Choose an event to move.")
            new_date = _date_or_none(request.POST.get("date"))
            if new_date is None:
                return HttpResponseBadRequest("Choose a valid date.")
            editing.date = new_date
            editing.save(update_fields=["date"])
            if editing.kind == AssessmentEvent.Kind.EXAM:
                sync_subject_next_exam(request, editing.subject)
            return redirect(f"{reverse('exams:calendar')}?date={new_date.isoformat()}")

        if request.POST.get("action") != "save":
            return HttpResponseBadRequest("Unknown action.")

        old_subject = editing.subject if editing is not None else None
        was_exam = editing is not None and editing.kind == AssessmentEvent.Kind.EXAM
        form = AssessmentEventForm(request.POST, instance=editing, user=request.user)
        if form.is_valid():
            event = form.save()
            if was_exam:
                sync_subject_next_exam(request, old_subject)
            if event.kind == AssessmentEvent.Kind.EXAM:
                sync_subject_next_exam(request, event.subject)
            return redirect(f"{reverse('exams:calendar')}?date={event.date.isoformat()}")

        selected_date = _date_or_none(request.POST.get("date")) or (
            editing.date if editing else today
        )
        return render(
            request,
            "exams/calendar.html",
            _calendar_context(request, selected_date, form, editing),
        )

    edit_id = request.GET.get("edit")
    if edit_id:
        editing = get_object_or_404(
            AssessmentEvent,
            pk=edit_id,
            subject__user=request.user,
        )
        selected_date = editing.date
    else:
        selected_date = (
            _date_or_none(request.GET.get("date"))
            or _month_or_none(request.GET.get("month"))
            or today
        )

    form = AssessmentEventForm(
        instance=editing,
        initial={"date": selected_date},
        user=request.user,
    )
    return render(
        request,
        "exams/calendar.html",
        _calendar_context(request, selected_date, form, editing),
    )

"""A read-only garden projection of the same work shown in Today's Plan."""

from datetime import timedelta
from urllib.parse import urlencode

from django.urls import reverse

from learning.models import Subject
from learning.garden_fruit import FRUIT_CHOICES
from learning.review_navigation import with_origin


CATEGORIES = (
    ("definitions", "Definitions", "definition_review_list", "top-left"),
    ("formulas", "Formulas", "formula_review_list", "middle-left"),
    ("lists", "Lists", "list_review_list", "bottom-left"),
    ("steps", "Steps", "step_review_list", "bottom-right"),
    ("comparisons", "Comparisons", "comparison_review_list", "middle-right"),
    ("notes", "Notes", "note_list", "top-right"),
)


def garden_state(user, session_subjects, groups, study_subjects, today):
    subjects = list(
        Subject.objects.filter(user=user)
        .order_by("created", "pk")
        .prefetch_related("study_textbooks", "assessment_events")
    )
    owned = {subject.pk: subject for subject in subjects}
    indexes = {subject.pk: index for index, subject in enumerate(subjects)}
    for index, entry in enumerate(session_subjects):
        try:
            subject_id = int(entry.get("database_id"))
        except (AttributeError, TypeError, ValueError):
            continue
        if subject_id in owned:
            indexes[subject_id] = index

    categories = []
    for key, label, route, origin in CATEGORIES:
        leaves = {}
        for item in groups.get(key, []):
            subject = item["subject"]
            if subject.pk not in owned:
                continue
            leaf = leaves.setdefault(subject.pk, {
                "id": f"{key}-{subject.pk}",
                "subject_id": subject.pk,
                "subject": owned[subject.pk].name,
                "count": 0,
                "url": with_origin((
                    reverse(route, kwargs={"subject_id": subject.pk})
                    + "?" + urlencode({"subject_index": indexes[subject.pk], "mode": "subject_review"})
                    if key == "notes"
                    else reverse(route, kwargs={"subject_index": indexes[subject.pk]})
                ), "garden"),
            })
            leaf["count"] += item.get("count", 0)
        categories.append({"id": key, "label": label, "origin": origin, "leaves": list(leaves.values())})

    today_pages = {item["subject"].pk: item.get("pages", 0) for item in study_subjects}
    trees = []
    for subject in subjects:
        books = list(subject.study_textbooks.all())
        total = sum(book.page_count for book in books)
        summarized = sum(min(book.page_count, book.pages_summarized) for book in books)
        ratio = 100 * summarized / total if total else 0
        progress = (100 if ratio == 100 else min(99.9, round(ratio, 1))) if total else None
        # Stage thresholds use the actual ratio, before rounding its label.
        if ratio == 0:
            stage = 0
        elif ratio <= 25:
            stage = 1
        elif ratio <= 50:
            stage = 2
        elif ratio <= 75:
            stage = 3
        elif ratio < 100:
            stage = 4
        else:
            stage = 5
        events = []
        for event in subject.assessment_events.all():
            if event.completed_at is not None:
                continue
            status = (
                "overdue" if event.date < today else
                "today" if event.date == today else
                "soon" if event.date <= today + timedelta(days=7) else "upcoming"
            )
            events.append({
                "id": event.pk, "title": event.title or event.get_kind_display(),
                "kind": event.kind, "type": event.get_kind_display(),
                "date": event.date.isoformat(), "date_label": event.date.strftime("%d %B %Y"),
                "status": status, "completed": event.completed_at is not None,
                "grounded": status == "overdue",
                "url": reverse("exams:calendar") + "?" + urlencode({"edit": event.pk}),
            })
        trees.append({
            "id": subject.pk, "subject": subject.name,
            "fruit": subject.garden_fruit or FRUIT_CHOICES[subject.pk % len(FRUIT_CHOICES)][0],
            "url": reverse("book_summary", kwargs={"subject_index": indexes[subject.pk]}),
            "total_pages": total, "summarized_pages": summarized,
            "progress": progress, "stage": stage,
            "today_pages": today_pages.get(subject.pk, 0), "events": events,
        })

    return {"student": user.pk, "date": today.isoformat(), "categories": categories, "trees": trees}

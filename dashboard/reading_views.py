"""Read-only browsing for the Review library's non-definition content."""

import json

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from learning.models import BulletList, Comparison, Formula, Note, StepList


REVIEW_TYPES = {
    "formula": (Formula, "review_formulas", "Formula"),
    "list": (BulletList, "review_lists", "List"),
    "step": (StepList, "review_steps", "Steps"),
    "note": (Note, "review_notes", "Note"),
    "comparison": (Comparison, "review_comparisons", "Comparison"),
}


@login_required
@require_GET
def read_review_item(request, kind, item_id):
    """Show full content and browse without creating or changing study progress."""
    if kind not in REVIEW_TYPES:
        raise Http404("Unknown review type")

    model, list_url_name, label = REVIEW_TYPES[kind]
    if kind == "note":
        items = model.objects.filter(subject__user=request.user).select_related(
            "subject"
        ).order_by("subject__name", "created", "pk")
        subject_field = "subject_id"
    else:
        items = model.objects.filter(
            knowledge_unit__subject__user=request.user,
            knowledge_unit__active=True,
        ).select_related("knowledge_unit__subject")
        if kind == "formula":
            items = items.prefetch_related("variables").order_by(
                "knowledge_unit__subject__name", "knowledge_unit__title", "pk"
            )
        else:
            items = items.order_by(
                "knowledge_unit__subject__name", "knowledge_unit__created", "pk"
            )
        subject_field = "knowledge_unit__subject_id"

    current = get_object_or_404(items, pk=item_id)
    subject = current.subject if kind == "note" else current.knowledge_unit.subject

    subject_id = request.GET.get("subject_id")
    if subject_id is not None:
        try:
            scoped_subject_id = int(subject_id)
        except ValueError:
            raise Http404("Invalid subject")
        if scoped_subject_id != subject.pk:
            raise Http404("Item is not in this subject")
        items = items.filter(**{subject_field: scoped_subject_id})

    item_ids = list(items.values_list("pk", flat=True))
    position = item_ids.index(current.pk)

    def read_url(pk):
        url = reverse("read_review_item", kwargs={"kind": kind, "item_id": pk})
        return f"{url}?subject_id={subject_id}" if subject_id is not None else url

    context = {
        "kind": kind,
        "label": label,
        "item": current,
        "subject": subject,
        "title": (
            current.title if kind == "note" else
            current.knowledge_unit.title if kind == "formula" else
            current.name if kind == "comparison" else current.question
        ),
        "position": position + 1,
        "total": len(item_ids),
        "previous_url": read_url(item_ids[position - 1]) if position else None,
        "next_url": read_url(item_ids[position + 1]) if position + 1 < len(item_ids) else None,
        "list_url": reverse(list_url_name) + "?mode=review",
    }

    if kind == "formula":
        try:
            formula_elements = json.loads(current.structure)
        except (json.JSONDecodeError, TypeError):
            formula_elements = []
        context["formula_elements"] = formula_elements if isinstance(formula_elements, list) else []
        context["variables"] = current.variables.order_by("order", "pk")
    elif kind == "list":
        context["entries"] = current.items.order_by("order", "pk")
    elif kind == "step":
        context["entries"] = current.steps.order_by("order", "pk")
    elif kind == "comparison":
        columns = list(current.columns.order_by("order", "pk"))
        rows = []
        for row in current.rows.order_by("order", "pk").prefetch_related("cells"):
            cells = {cell.column_id: cell.content for cell in row.cells.all()}
            rows.append({"name": row.name, "values": [cells.get(col.pk, "") for col in columns]})
        context.update({"columns": columns, "rows": rows})

    return render(request, "dashboard/read_review_item.html", context)

"""Validate and save reviewed PDF suggestions as ordinary learning items."""

from learning.models import (
    BulletItem, BulletList, Comparison, ComparisonCell, ComparisonColumn,
    ComparisonRow, KnowledgeUnit, Note, StepItem, StepList,
)


KINDS = ("list", "steps", "note", "comparison")
LABELS = {"list": "list", "steps": "step sequence", "note": "note", "comparison": "comparison"}
MODELS = {"list": BulletList, "steps": StepList, "comparison": Comparison}
NAME_FIELDS = {"list": "question", "steps": "question", "comparison": "name"}


def _text(value, limit, field):
    if not isinstance(value, str):
        raise ValueError(f"The {field} must be text.")
    value = value.strip()
    if not value or len(value) > limit:
        raise ValueError(f"The {field} is empty or too long. Review this suggestion before adding it.")
    return value


def normalize_candidate(kind, candidate):
    """Return a bounded payload safe for the existing learning-item schema."""
    if kind not in KINDS or not isinstance(candidate, dict):
        raise ValueError("Choose a valid learning item from this scan.")
    result = {"title": _text(candidate.get("title"), 255, "title")}
    if kind in {"list", "steps"}:
        source = candidate.get("items" if kind == "list" else "steps")
        if not isinstance(source, list) or not 1 <= len(source) <= 20:
            raise ValueError("This suggestion needs between 1 and 20 entries.")
        entries = []
        for entry in source:
            if not isinstance(entry, dict):
                raise ValueError("An entry in this suggestion is incomplete.")
            description = entry.get("description", "")
            if not isinstance(description, str) or len(description.strip()) > 500:
                raise ValueError("An entry description is too long.")
            entries.append({
                "text": _text(entry.get("text"), 255, "entry"),
                "description": description.strip(),
            })
        result["items" if kind == "list" else "steps"] = entries
    elif kind == "note":
        result["content"] = _text(candidate.get("content"), 10000, "note content")
    else:
        columns = candidate.get("columns")
        rows = candidate.get("rows")
        if not isinstance(columns, list) or len(columns) != 2:
            raise ValueError("This comparison needs exactly two columns.")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
            raise ValueError("This comparison needs between 1 and 20 rows.")
        result["columns"] = [_text(name, 255, "column name") for name in columns]
        result["rows"] = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("cells"), list) or len(row["cells"]) != 2:
                raise ValueError("A comparison row is incomplete.")
            cells = row["cells"]
            result["rows"].append({
                "name": _text(row.get("name"), 255, "row name"),
                "cells": [_text(value, 2000, "comparison cell") for value in cells],
            })
    return result


def _stored_payload(kind, instance):
    """Read an existing item in the same shape used by the manual editors."""
    if kind == "list":
        return {
            "title": instance.question,
            "items": [
                {"text": entry.text, "description": entry.description}
                for entry in instance.items.all().order_by("order", "id")
            ],
        }
    if kind == "steps":
        return {
            "title": instance.question,
            "steps": [
                {"text": entry.text, "description": entry.description}
                for entry in instance.steps.all().order_by("order", "id")
            ],
        }

    columns = list(instance.columns.all().order_by("order", "id"))
    rows = []
    for row in instance.rows.all().order_by("order", "id"):
        cells = {cell.column_id: cell.content for cell in row.cells.all()}
        rows.append({
            "name": row.name,
            "cells": [cells.get(column.pk, "") for column in columns],
        })
    return {
        "title": instance.name,
        "columns": [column.name for column in columns],
        "rows": rows,
    }


def _matching_existing(subject, kind, item, book_name, chapter):
    """Only deduplicate a byte-for-byte equivalent structured learning item."""
    model = MODELS[kind]
    name_field = NAME_FIELDS[kind]
    queryset = model.objects.filter(
        knowledge_unit__subject=subject,
        knowledge_unit__active=True,
        book_name=book_name,
        chapter=chapter,
        **{name_field + "__iexact": item["title"]},
    )
    if kind == "list":
        queryset = queryset.prefetch_related("items")
    elif kind == "steps":
        queryset = queryset.prefetch_related("steps")
    else:
        queryset = queryset.prefetch_related("columns", "rows__cells")
    for instance in queryset:
        stored = _stored_payload(kind, instance)
        same_title = stored.pop("title").casefold() == item["title"].casefold()
        expected = {key: value for key, value in item.items() if key != "title"}
        if same_title and stored == expected:
            return instance
    return None


def _create_list(subject, item, book_name, chapter):
    unit = KnowledgeUnit.objects.create(
        subject=subject,
        title=item["title"],
        knowledge_type=KnowledgeUnit.KnowledgeType.BULLET_LIST,
        difficulty=1,
        estimated_minutes=max(2, len(item["items"])),
        active=True,
    )
    bullet_list = BulletList.objects.create(
        knowledge_unit=unit,
        question=item["title"],
        book_name=book_name,
        chapter=chapter,
    )
    for position, entry in enumerate(item["items"], 1):
        BulletItem.objects.create(
            bullet_list=bullet_list,
            text=entry["text"],
            description=entry["description"],
            order=position,
        )
    return bullet_list


def _create_steps(subject, item, book_name, chapter):
    # Deliberately mirror learning.views.create_steps. In particular, the
    # KnowledgeUnit keeps the model's ordinary defaults and each StepItem is
    # saved with the same fields and ordering as a manually entered sequence.
    unit = KnowledgeUnit.objects.create(
        subject=subject,
        title=item["title"],
        knowledge_type=KnowledgeUnit.KnowledgeType.STEPS,
        active=True,
    )
    step_list = StepList.objects.create(
        knowledge_unit=unit,
        question=item["title"],
        book_name=book_name,
        chapter=chapter,
    )
    for position, entry in enumerate(item["steps"], 1):
        StepItem.objects.create(
            step_list=step_list,
            text=entry["text"],
            description=entry["description"],
            order=position,
        )
    return step_list


def _create_comparison(subject, item, book_name, chapter):
    # This is the same normalized two-dimensional structure used by the
    # comparison editor: ordered columns, ordered rows and one cell per pair.
    unit = KnowledgeUnit.objects.create(
        subject=subject,
        title=item["title"],
        knowledge_type=KnowledgeUnit.KnowledgeType.COMPARISON,
        difficulty=1,
        estimated_minutes=max(2, len(item["rows"])),
        active=True,
    )
    comparison = Comparison.objects.create(
        knowledge_unit=unit,
        name=item["title"],
        book_name=book_name,
        chapter=chapter,
    )
    columns = [
        ComparisonColumn.objects.create(
            comparison=comparison,
            name=name,
            order=position,
        )
        for position, name in enumerate(item["columns"], 1)
    ]
    for position, row_data in enumerate(item["rows"], 1):
        row = ComparisonRow.objects.create(
            comparison=comparison,
            name=row_data["name"],
            order=position,
        )
        for column_index, column in enumerate(columns):
            ComparisonCell.objects.create(
                row=row,
                column=column,
                content=row_data["cells"][column_index],
            )
    return comparison


def import_candidate(subject, kind, candidate, book_name="", chapter=""):
    """Return (object id, created). Caller holds an atomic transaction."""
    item = normalize_candidate(kind, candidate)
    title = item["title"]
    if kind == "note":
        existing = Note.objects.filter(
            subject=subject, title__iexact=title,
            content=item["content"], book_name=book_name, chapter=chapter,
        ).first()
        if existing:
            return existing.pk, False
        note = Note.objects.create(
            subject=subject, title=title, content=item["content"],
            book_name=book_name, chapter=chapter,
        )
        return note.pk, True

    existing = _matching_existing(subject, kind, item, book_name, chapter)
    if existing:
        return existing.pk, False

    if kind == "list":
        instance = _create_list(subject, item, book_name, chapter)
    elif kind == "steps":
        instance = _create_steps(subject, item, book_name, chapter)
    else:
        instance = _create_comparison(subject, item, book_name, chapter)
    return instance.pk, True

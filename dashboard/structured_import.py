"""Validate and save reviewed PDF suggestions as ordinary learning items."""

from learning.models import (
    BulletItem, BulletList, Comparison, ComparisonCell, ComparisonColumn,
    ComparisonRow, KnowledgeUnit, Note, StepItem, StepList,
)


KINDS = ("list", "steps", "note", "comparison")
LABELS = {"list": "list", "steps": "step sequence", "note": "note", "comparison": "comparison"}
MODELS = {"list": BulletList, "steps": StepList, "comparison": Comparison}
NAME_FIELDS = {"list": "question", "steps": "question", "comparison": "name"}
KNOWLEDGE_TYPES = {
    "list": KnowledgeUnit.KnowledgeType.BULLET_LIST,
    "steps": KnowledgeUnit.KnowledgeType.STEPS,
    "comparison": KnowledgeUnit.KnowledgeType.COMPARISON,
}


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

    model = MODELS[kind]
    name_field = NAME_FIELDS[kind]
    existing = model.objects.filter(
        knowledge_unit__subject=subject,
        knowledge_unit__active=True,
        book_name=book_name, chapter=chapter,
        **{name_field + "__iexact": title},
    ).first()
    if existing:
        return existing.pk, False

    size = len(item.get("items") or item.get("steps") or item.get("rows") or [])
    unit = KnowledgeUnit.objects.create(
        subject=subject, title=title, knowledge_type=KNOWLEDGE_TYPES[kind],
        difficulty=1, estimated_minutes=max(2, size), active=True,
    )
    instance = model.objects.create(
        knowledge_unit=unit, book_name=book_name, chapter=chapter,
        **{name_field: title},
    )
    if kind == "list":
        BulletItem.objects.bulk_create([
            BulletItem(bullet_list=instance, order=position, **entry)
            for position, entry in enumerate(item["items"], 1)
        ])
    elif kind == "steps":
        StepItem.objects.bulk_create([
            StepItem(step_list=instance, order=position, **entry)
            for position, entry in enumerate(item["steps"], 1)
        ])
    else:
        columns = [
            ComparisonColumn.objects.create(comparison=instance, name=name, order=position)
            for position, name in enumerate(item["columns"], 1)
        ]
        for position, row_data in enumerate(item["rows"], 1):
            row = ComparisonRow.objects.create(
                comparison=instance, name=row_data["name"], order=position,
            )
            for column, content in zip(columns, row_data["cells"]):
                ComparisonCell.objects.create(row=row, column=column, content=content)
    return instance.pk, True

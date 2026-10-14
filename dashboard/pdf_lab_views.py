"""Superuser-only experiment for inspecting learning items in uploaded PDFs."""

import json
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from learning.models import Definition, Formula, FormulaVariable, KnowledgeUnit, Subject

from .definition_detection import find_definition_candidates
from .formula_detection import equation_to_structure, find_formula_candidates
from .models import SubjectTextbook
from .pdf_image_ocr import MAX_OCR_IMAGES_PER_SCAN, scan_page_images
from .pdf_lab_session import KIND_KEYS, SESSION_KEY, get_candidate, get_scan, mark_saved, save_scan
from .structured_detection import (
    find_comparison_candidates, find_list_candidates,
    find_note_candidates, find_step_candidates,
)
from .structured_import import KINDS, LABELS, import_candidate, normalize_candidate


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PAGES_PER_SCAN = 50
MAX_CANDIDATES = 300


def _candidate_values(candidate):
    term = str(candidate.get("term", "")).strip()
    definition = str(candidate.get("definition", "")).strip()
    if not term or not definition or len(term) > 255 or len(definition) > 1200:
        raise ValueError("A definition in this scan is incomplete. Scan the PDF again.")
    return term, definition


def _import_candidates(request, subject, state, indexes):
    """Create ordinary reviewable definitions; repeat imports are idempotent."""
    candidates = state["scan"]["candidates"]
    saved = dict(state.get("saved") or {})
    created = 0
    already_present = 0

    with transaction.atomic():
        Subject.objects.select_for_update().get(pk=subject.pk)
        # Match by term so a corrected definition is not reimported from the
        # original PDF when the same chapter is scanned again.
        existing = {
            term.casefold(): pk
            for pk, term in Definition.objects.filter(
                knowledge_unit__subject=subject,
                knowledge_unit__active=True,
            ).values_list("pk", "term")
        }
        for index in indexes:
            if str(index) in saved:
                already_present += 1
                continue
            term, definition_text = _candidate_values(candidates[index])
            key = term.casefold()
            definition_id = existing.get(key)
            if definition_id is None:
                unit = KnowledgeUnit.objects.create(
                    subject=subject,
                    title=term,
                    knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
                    difficulty=1,
                    estimated_minutes=2,
                    active=True,
                )
                definition_id = Definition.objects.create(
                    knowledge_unit=unit,
                    term=term,
                    definition=definition_text,
                    book_name=state.get("book_name", ""),
                    chapter=state.get("chapter", ""),
                ).pk
                existing[key] = definition_id
                created += 1
            else:
                already_present += 1
            saved[str(index)] = definition_id

    state["saved"] = saved
    request.session[SESSION_KEY] = state
    return created, already_present


def _import_formulas(request, subject, state, indexes):
    """Create editable, reviewable formulas without importing duplicates."""
    candidates = state["scan"].get("formula_candidates", [])
    saved = dict(state.get("saved_formulas") or {})
    created = already_present = 0
    with transaction.atomic():
        Subject.objects.select_for_update().get(pk=subject.pk)
        existing = {
            formula.knowledge_unit.title.casefold(): formula.pk
            for formula in Formula.objects.filter(
                knowledge_unit__subject=subject,
                knowledge_unit__active=True,
            ).select_related("knowledge_unit")
        }
        for index in indexes:
            if str(index) in saved:
                already_present += 1
                continue
            candidate = candidates[index]
            title = str(candidate.get("title", "")).strip()
            equation = str(candidate.get("equation", "")).strip()
            if not title or len(title) > 255:
                raise ValueError("A formula in this scan is incomplete. Scan the PDF again.")
            # Re-parse the PDF expression rather than trusting mutable session data.
            structure = equation_to_structure(equation)
            key = title.casefold()
            formula_id = existing.get(key)
            if formula_id is None:
                unit = KnowledgeUnit.objects.create(
                    subject=subject, title=title,
                    knowledge_type=KnowledgeUnit.KnowledgeType.FORMULA,
                    difficulty=1, estimated_minutes=2, active=True,
                )
                formula = Formula.objects.create(
                    knowledge_unit=unit,
                    structure=json.dumps(structure, ensure_ascii=False),
                    book_name=state.get("book_name", ""),
                    chapter=state.get("chapter", ""),
                )
                seen_symbols = set()
                for element in structure:
                    if element["type"] != "variable":
                        continue
                    symbol = element["value"]
                    if symbol.casefold() in seen_symbols:
                        continue
                    seen_symbols.add(symbol.casefold())
                    FormulaVariable.objects.create(
                        formula=formula, symbol=symbol, meaning="",
                        order=len(seen_symbols),
                    )
                formula_id = formula.pk
                existing[key] = formula_id
                created += 1
            else:
                already_present += 1
            saved[str(index)] = formula_id
    state["saved_formulas"] = saved
    request.session[SESSION_KEY] = state
    return created, already_present


def _import_structured(request, subject, state, kind, indexes):
    candidates_key, saved_key = KIND_KEYS[kind]
    candidates = state["scan"].get(candidates_key, [])
    saved = dict(state.get(saved_key) or {})
    created = already_present = 0
    with transaction.atomic():
        Subject.objects.select_for_update().get(pk=subject.pk)
        for index in indexes:
            if str(index) in saved:
                already_present += 1
                continue
            item_id, was_created = import_candidate(
                subject, kind, candidates[index],
                state.get("book_name", ""), state.get("chapter", ""),
            )
            saved[str(index)] = item_id
            created += int(was_created)
            already_present += int(not was_created)
    state[saved_key] = saved
    request.session[SESSION_KEY] = state
    return created, already_present


def _display_scan(context, state):
    if state is None:
        return
    scan = state["scan"]
    saved = state.get("saved") or {}
    saved_formulas = state.get("saved_formulas") or {}
    structured_edit_names = {
        "list": "edit_list", "steps": "edit_steps",
        "note": "edit_note", "comparison": "edit_comparison",
    }
    structured_display = {}
    for kind in KINDS:
        candidate_key, saved_key = KIND_KEYS[kind]
        saved_items = state.get(saved_key) or {}
        decorated = []
        for index, item in enumerate(scan.get(candidate_key, [])):
            saved_id = saved_items.get(str(index))
            decorated.append({
                **item, "index": index, "saved_id": saved_id,
                "saved_edit_url": (
                    reverse(structured_edit_names[kind], args=[saved_id])
                    if saved_id else ""
                ),
                "edit_before_url": (
                    reverse("edit_pdf_suggestion", args=[state["subject_id"], kind, index])
                    + "?scan_id=" + state["id"]
                ),
            })
        structured_display[candidate_key] = decorated
    context["scan"] = {
        **scan,
        "candidates": [
            {**item, "index": index, "saved_definition_id": saved.get(str(index))}
            for index, item in enumerate(scan["candidates"])
        ],
        "formula_candidates": [
            {**item, "index": index, "saved_formula_id": saved_formulas.get(str(index))}
            for index, item in enumerate(scan.get("formula_candidates", []))
        ],
        **structured_display,
    }
    context["scan_id"] = state["id"]
    context["file_name"] = state["file_name"]
    context["selected_book"] = state.get("book_name", "")
    context["chapter"] = state.get("chapter", "")


def _subject_index(request, subject):
    for index, item in enumerate(request.session.get("onboarding_subjects", [])):
        if isinstance(item, dict) and str(item.get("database_id")) == str(subject.pk):
            return index
    return None


def _subject_back_url(request, subject):
    index = _subject_index(request, subject)
    return reverse("subject_detail", args=[index]) if index is not None else reverse("goals")


def _scan_pdf(upload, start_page, pages_to_scan):
    upload.seek(0)
    reader = PdfReader(upload, strict=False)
    if reader.is_encrypted:
        raise ValueError("Password-protected PDFs are not supported yet.")
    total_pages = len(reader.pages)
    if total_pages == 0:
        raise ValueError("This PDF has no pages.")
    if start_page > total_pages:
        raise ValueError(f"Start page must be between 1 and {total_pages}.")

    last_page = min(total_pages, start_page + pages_to_scan - 1)
    results, formula_results = [], []
    seen, seen_formulas = set(), set()
    structured = {KIND_KEYS[kind][0]: [] for kind in KINDS}
    seen_structured = {kind: set() for kind in KINDS}
    structured_truncated = {kind: False for kind in KINDS}
    text_pages = 0
    image_pages = image_text_pages = images_checked = 0
    image_ocr_unavailable = image_limit_reached = False
    text_sample = ""
    truncated = formula_truncated = False
    scanned_through = start_page - 1

    def add_detected(text, layout_text, page_number, source):
        nonlocal truncated, formula_truncated
        for candidate in find_definition_candidates(text[:100_000], page_number):
            key = (
                candidate["term"].casefold(),
                " ".join(candidate["definition"].casefold().split()),
            )
            if key in seen:
                continue
            seen.add(key)
            if len(results) >= MAX_CANDIDATES:
                truncated = True
                break
            if source == "image":
                candidate = {**candidate, "source": "image", "confidence": "possible"}
            results.append(candidate)
        for candidate in find_formula_candidates(text[:100_000], page_number):
            key = "".join(candidate["equation"].casefold().split())
            if key in seen_formulas:
                continue
            seen_formulas.add(key)
            if len(formula_results) >= MAX_CANDIDATES:
                formula_truncated = True
                break
            if source == "image":
                candidate = {**candidate, "source": "image", "confidence": "possible"}
            formula_results.append(candidate)
        detectors = {
            "list": find_list_candidates(layout_text[:100_000], page_number),
            "steps": find_step_candidates(layout_text[:100_000], page_number),
            "note": find_note_candidates(layout_text[:100_000], page_number),
            "comparison": find_comparison_candidates(layout_text[:100_000], page_number),
        }
        for kind, candidates in detectors.items():
            bucket = structured[KIND_KEYS[kind][0]]
            for candidate in candidates:
                key = json.dumps(
                    {field: value for field, value in candidate.items() if field not in {"page", "confidence", "source"}},
                    sort_keys=True, ensure_ascii=False,
                )
                if key in seen_structured[kind]:
                    continue
                seen_structured[kind].add(key)
                if len(bucket) >= MAX_CANDIDATES:
                    structured_truncated[kind] = True
                    break
                if source == "image":
                    candidate = {**candidate, "source": "image", "confidence": "possible"}
                bucket.append(candidate)

    for page_number in range(start_page, last_page + 1):
        scanned_through = page_number
        try:
            text = reader.pages[page_number - 1].extract_text() or ""
        except (PdfReadError, ValueError, TypeError, KeyError, IndexError) as exc:
            raise ValueError(f"Could not read page {page_number} of this PDF.") from exc
        if text.strip():
            text_pages += 1
            if not text_sample:
                text_sample = " ".join(text.split())[:900]
            try:
                layout_text = reader.pages[page_number - 1].extract_text(extraction_mode="layout") or text
            except (PdfReadError, ValueError, TypeError, KeyError, IndexError):
                layout_text = text
            add_detected(text, layout_text, page_number, "text")

        if not image_ocr_unavailable:
            image_scan = scan_page_images(
                reader.pages[page_number - 1], MAX_OCR_IMAGES_PER_SCAN - images_checked,
            )
            image_pages += int(image_scan["image_found"])
            images_checked += image_scan["checked"]
            image_ocr_unavailable = image_scan["unavailable"]
            image_limit_reached |= image_scan["limit_reached"]
            if image_scan["texts"]:
                image_text_pages += 1
            for image_text in image_scan["texts"]:
                if not text_sample:
                    text_sample = " ".join(image_text.split())[:900]
                add_detected(image_text, image_text, page_number, "image")
        if truncated and formula_truncated and all(structured_truncated.values()):
            break

    return {
        "total_pages": total_pages,
        "start_page": start_page,
        "last_page": scanned_through,
        "pages_scanned": scanned_through - start_page + 1,
        "text_pages": text_pages,
        "image_pages": image_pages,
        "image_text_pages": image_text_pages,
        "images_checked": images_checked,
        "image_ocr_unavailable": image_ocr_unavailable,
        "image_limit_reached": image_limit_reached,
        "candidates": results,
        "formula_candidates": formula_results,
        **structured,
        "text_sample": text_sample,
        "truncated": truncated,
        "formula_truncated": formula_truncated,
        "structured_truncated": any(structured_truncated.values()),
    }


@login_required
@require_http_methods(["GET", "POST"])
def definition_pdf_lab(request, subject_id):
    if not request.user.is_superuser:
        raise Http404()
    subject = get_object_or_404(Subject, pk=subject_id, user=request.user)
    context = {
        "subject": subject,
        "back_url": _subject_back_url(request, subject),
        "subject_index": _subject_index(request, subject) or 0,
        "max_pages": MAX_PAGES_PER_SCAN,
        "max_size_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        "start_page": 1,
        "pages_to_scan": 25,
        "textbooks": SubjectTextbook.objects.filter(subject=subject).order_by("created", "id"),
        "selected_book": "",
        "chapter": "",
    }
    state = get_scan(request, subject.pk)
    if request.method == "POST":
        action = request.POST.get("action", "scan")
        structured_actions = {
            f"add_{kind}_{mode}"
            for kind in KINDS for mode in ("one", "all")
        }
        if action in {"add_one", "add_all", "add_formula_one", "add_formula_all"} | structured_actions:
            state = get_scan(request, subject.pk, request.POST.get("scan_id") or "")
            if state is None:
                context["error"] = "This PDF preview is no longer available. Scan the PDF again."
            else:
                try:
                    kind = (
                        "formula" if action.startswith("add_formula")
                        else action[4:].rsplit("_", 1)[0] if action in structured_actions
                        else "definition"
                    )
                    candidates = state["scan"].get(KIND_KEYS[kind][0], [])
                    if action.endswith("one"):
                        index = int(request.POST.get("candidate_index", ""))
                        if not 0 <= index < len(candidates):
                            raise ValueError("Choose an item from the current scan.")
                        indexes = [index]
                    else:
                        indexes = range(len(candidates))
                    if kind in KINDS:
                        created, already_present = _import_structured(
                            request, subject, state, kind, indexes,
                        )
                    else:
                        import_items = _import_formulas if kind == "formula" else _import_candidates
                        created, already_present = import_items(
                            request, subject, state, indexes,
                        )
                    item_name = LABELS.get(kind, kind)
                    messages.success(
                        request,
                        f"{created} {item_name}{'s' if created != 1 else ''} added to "
                        f"{subject.name}."
                        + (f" {already_present} already added or present." if already_present else ""),
                    )
                    return redirect("definition_pdf_lab", subject_id=subject.pk)
                except (TypeError, ValueError, IndexError) as exc:
                    context["error"] = str(exc) or "Could not add this item."
        elif action == "scan":
            upload = request.FILES.get("pdf_file")
            context["start_page"] = request.POST.get("start_page", "1")
            context["pages_to_scan"] = request.POST.get("pages_to_scan", "25")
            context["selected_book"] = request.POST.get("book_name", "").strip()
            context["chapter"] = request.POST.get("chapter", "").strip()
            try:
                if context["selected_book"] and not SubjectTextbook.objects.filter(
                    subject=subject, name=context["selected_book"]
                ).exists():
                    raise ValueError("The selected textbook does not belong to this subject.")
                if len(context["chapter"]) > 255:
                    raise ValueError("The chapter cannot be longer than 255 characters.")
                start_page = int(context["start_page"])
                pages_to_scan = int(context["pages_to_scan"])
                if start_page < 1 or not 1 <= pages_to_scan <= MAX_PAGES_PER_SCAN:
                    raise ValueError(
                        f"Choose a start page of at least 1 and scan 1-{MAX_PAGES_PER_SCAN} pages."
                    )
                if upload is None:
                    raise ValueError("Choose a PDF to scan.")
                if not Path(upload.name).name.lower().endswith(".pdf"):
                    raise ValueError("Choose a .pdf file.")
                if upload.size > MAX_UPLOAD_BYTES:
                    raise ValueError(
                        f"The PDF must be {context['max_size_mb']} MB or smaller."
                    )
                if b"%PDF-" not in upload.read(1024):
                    raise ValueError("This file does not look like a valid PDF.")
                state = save_scan(
                    request, subject.pk, _scan_pdf(upload, start_page, pages_to_scan),
                    Path(upload.name).name,
                    context["selected_book"], context["chapter"],
                )
            except (PdfReadError, ValueError, OSError, IndexError) as exc:
                context["error"] = str(exc) or "Could not read this PDF."
        else:
            context["error"] = "Choose a valid action."

    _display_scan(context, state)
    return render(request, "dashboard/definition_pdf_lab.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def edit_pdf_suggestion(request, subject_id, kind, index):
    """Review and correct a structured suggestion before saving it."""
    if not request.user.is_superuser or kind not in KINDS:
        raise Http404()
    subject = get_object_or_404(Subject, pk=subject_id, user=request.user)
    scan_id = request.POST.get("scan_id") if request.method == "POST" else request.GET.get("scan_id")
    state = get_scan(request, subject.pk, scan_id or "")
    candidate = get_candidate(request, subject.pk, scan_id or "", index, kind)
    if state is None or candidate is None:
        messages.error(request, "This PDF preview has expired. Scan the PDF again.")
        return redirect("definition_pdf_lab", subject_id=subject.pk)
    saved_id = (state.get(KIND_KEYS[kind][1]) or {}).get(str(index))
    if saved_id:
        edit_names = {
            "list": "edit_list", "steps": "edit_steps",
            "note": "edit_note", "comparison": "edit_comparison",
        }
        return redirect(edit_names[kind], saved_id)

    try:
        item = normalize_candidate(kind, candidate)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("definition_pdf_lab", subject_id=subject.pk)
    book_name = state.get("book_name", "")
    chapter = state.get("chapter", "")
    error = None
    textbooks = SubjectTextbook.objects.filter(subject=subject).order_by("created", "id")
    if request.method == "POST":
        book_name = request.POST.get("book_name", "").strip()
        chapter = request.POST.get("chapter", "").strip()
        item["title"] = request.POST.get("title", "").strip()
        if kind in {"list", "steps"}:
            texts = request.POST.getlist("entry_text")
            descriptions = request.POST.getlist("entry_description")
            item["items" if kind == "list" else "steps"] = [
                {"text": text.strip(), "description": (
                    descriptions[position].strip() if position < len(descriptions) else ""
                )}
                for position, text in enumerate(texts) if text.strip()
            ]
        elif kind == "note":
            item["content"] = request.POST.get("content", "").strip()
        else:
            item["columns"] = [name.strip() for name in request.POST.getlist("column_name")]
            row_names = request.POST.getlist("row_name")
            left_cells = request.POST.getlist("cell_left")
            right_cells = request.POST.getlist("cell_right")
            item["rows"] = [
                {"name": name.strip(), "cells": [
                    left_cells[position].strip() if position < len(left_cells) else "",
                    right_cells[position].strip() if position < len(right_cells) else "",
                ]}
                for position, name in enumerate(row_names) if name.strip()
            ]
        try:
            if book_name and not textbooks.filter(name=book_name).exists():
                raise ValueError("The selected textbook does not belong to this subject.")
            if len(chapter) > 255:
                raise ValueError("The chapter cannot be longer than 255 characters.")
            item = normalize_candidate(kind, item)
            with transaction.atomic():
                Subject.objects.select_for_update().get(pk=subject.pk)
                item_id, created = import_candidate(
                    subject, kind, item, book_name, chapter,
                )
            mark_saved(request, subject.pk, scan_id, index, item_id, kind=kind)
            messages.success(request, f"{'Added' if created else 'Already present'}: {item['title']}.")
            return redirect("definition_pdf_lab", subject_id=subject.pk)
        except ValueError as exc:
            error = str(exc)
    return render(request, "dashboard/edit_pdf_suggestion.html", {
        "subject": subject, "kind": kind, "label": LABELS[kind], "item": item,
        "scan_id": scan_id, "index": index, "book_name": book_name,
        "chapter": chapter, "textbooks": textbooks, "error": error,
        "back_url": reverse("definition_pdf_lab", args=[subject.pk]),
    })

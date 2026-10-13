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
from .pdf_lab_session import SESSION_KEY, get_scan, save_scan


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


def _display_scan(context, state):
    if state is None:
        return
    scan = state["scan"]
    saved = state.get("saved") or {}
    saved_formulas = state.get("saved_formulas") or {}
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
    text_pages = 0
    text_sample = ""
    truncated = formula_truncated = False
    scanned_through = start_page - 1
    for page_number in range(start_page, last_page + 1):
        scanned_through = page_number
        try:
            text = reader.pages[page_number - 1].extract_text() or ""
        except (PdfReadError, ValueError, TypeError, KeyError, IndexError) as exc:
            raise ValueError(f"Could not read page {page_number} of this PDF.") from exc
        if not text.strip():
            continue
        text_pages += 1
        if not text_sample:
            text_sample = " ".join(text.split())[:900]
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
            results.append(candidate)
        for candidate in find_formula_candidates(text[:100_000], page_number):
            key = "".join(candidate["equation"].casefold().split())
            if key in seen_formulas:
                continue
            seen_formulas.add(key)
            if len(formula_results) >= MAX_CANDIDATES:
                formula_truncated = True
                break
            formula_results.append(candidate)
        if truncated and formula_truncated:
            break

    return {
        "total_pages": total_pages,
        "start_page": start_page,
        "last_page": scanned_through,
        "pages_scanned": scanned_through - start_page + 1,
        "text_pages": text_pages,
        "candidates": results,
        "formula_candidates": formula_results,
        "text_sample": text_sample,
        "truncated": truncated,
        "formula_truncated": formula_truncated,
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
        if action in {"add_one", "add_all", "add_formula_one", "add_formula_all"}:
            state = get_scan(request, subject.pk, request.POST.get("scan_id") or "")
            if state is None:
                context["error"] = "This PDF preview is no longer available. Scan the PDF again."
            else:
                try:
                    formula_action = action.startswith("add_formula")
                    candidates = state["scan"].get(
                        "formula_candidates" if formula_action else "candidates", []
                    )
                    if action.endswith("one"):
                        index = int(request.POST.get("candidate_index", ""))
                        if not 0 <= index < len(candidates):
                            raise ValueError("Choose an item from the current scan.")
                        indexes = [index]
                    else:
                        indexes = range(len(candidates))
                    import_items = _import_formulas if formula_action else _import_candidates
                    created, already_present = import_items(
                        request, subject, state, indexes,
                    )
                    item_name = "formula" if formula_action else "definition"
                    messages.success(
                        request,
                        f"{created} {item_name}{'s' if created != 1 else ''} added to "
                        f"{subject.name}."
                        + (f" {already_present} already added or present." if already_present else ""),
                    )
                    return redirect("definition_pdf_lab", subject_id=subject.pk)
                except (TypeError, ValueError, IndexError) as exc:
                    context["error"] = str(exc) or "Could not add this definition."
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

"""Superuser-only experiment for inspecting definitions in uploaded PDFs."""

from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from learning.models import Subject

from .definition_detection import find_definition_candidates


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PAGES_PER_SCAN = 50
MAX_CANDIDATES = 300


def _subject_back_url(request, subject):
    for index, item in enumerate(request.session.get("onboarding_subjects", [])):
        if isinstance(item, dict) and str(item.get("database_id")) == str(subject.pk):
            return reverse("subject_detail", args=[index])
    return reverse("goals")


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
    results = []
    seen = set()
    text_pages = 0
    text_sample = ""
    truncated = False
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
        if truncated:
            break

    return {
        "total_pages": total_pages,
        "start_page": start_page,
        "last_page": scanned_through,
        "pages_scanned": scanned_through - start_page + 1,
        "text_pages": text_pages,
        "candidates": results,
        "text_sample": text_sample,
        "truncated": truncated,
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
        "max_pages": MAX_PAGES_PER_SCAN,
        "max_size_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        "start_page": 1,
        "pages_to_scan": 25,
    }
    if request.method == "POST":
        upload = request.FILES.get("pdf_file")
        context["start_page"] = request.POST.get("start_page", "1")
        context["pages_to_scan"] = request.POST.get("pages_to_scan", "25")
        try:
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
            context["scan"] = _scan_pdf(upload, start_page, pages_to_scan)
            context["file_name"] = Path(upload.name).name
        except (PdfReadError, ValueError, OSError, IndexError) as exc:
            context["error"] = str(exc) or "Could not read this PDF."

    return render(request, "dashboard/definition_pdf_lab.html", context)

"""Private, on-demand PDF exports of a student's saved subject material."""

import io
import json
import re
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET
from reportlab import __file__ as reportlab_path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

from learning.models import KnowledgeUnit, Note, Subject


TYPE_ORDER = (
    (KnowledgeUnit.KnowledgeType.DEFINITION, "Definitions", "definition"),
    (KnowledgeUnit.KnowledgeType.FORMULA, "Formulas", "formula"),
    (KnowledgeUnit.KnowledgeType.BULLET_LIST, "Lists", "bullet_list"),
    (KnowledgeUnit.KnowledgeType.STEPS, "Steps", "step_list"),
    (KnowledgeUnit.KnowledgeType.COMPARISON, "Comparisons", "comparison"),
    ("NOTE", "Notes", None),
)
def _font_names():
    """Use an embedded Unicode font in production; keep local previews usable."""
    candidates = (
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
        (Path("C:/Windows/Fonts/segoeui.ttf"),
         Path("C:/Windows/Fonts/segoeuib.ttf")),
        (Path(reportlab_path).parent / "fonts" / "Vera.ttf",
         Path(reportlab_path).parent / "fonts" / "VeraBd.ttf"),
    )
    regular, bold = next(
        ((regular, bold) for regular, bold in candidates
         if regular.is_file() and bold.is_file()),
        (None, None),
    )
    if regular is None:
        raise RuntimeError("No font available for summary PDF exports")
    if "StudyGarden" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("StudyGarden", str(regular)))
        pdfmetrics.registerFont(TTFont("StudyGarden-Bold", str(bold)))
        pdfmetrics.registerFontFamily(
            "StudyGarden", normal="StudyGarden", bold="StudyGarden-Bold"
        )
    return "StudyGarden", "StudyGarden-Bold"


def _safe(value):
    return escape(str(value or "")).replace("\n", "<br/>")


def _natural_sort_key(value):
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", value.casefold())
    )


def _formula_text(structure):
    try:
        elements = json.loads(structure)
    except (TypeError, ValueError):
        return "Formula not available"

    def render(parts, depth=0):
        if not isinstance(parts, list) or depth > 12:
            return ""
        result = []
        for element in parts:
            if not isinstance(element, dict):
                continue
            if element.get("type") == "fraction":
                numerator = render(element.get("numerator"), depth + 1) or "?"
                denominator = render(element.get("denominator"), depth + 1) or "?"
                result.append(f"({numerator}) / ({denominator})")
            else:
                value = element.get("value")
                if value is None or value == "":
                    value = element.get("symbol") or element.get("text")
                if value is not None:
                    result.append(str(value))
        return " ".join(result)

    return render(elements) or "No formula entered"


def _collect_items(subject):
    units = (
        KnowledgeUnit.objects.filter(subject=subject, active=True)
        .select_related("definition", "formula", "bullet_list", "step_list", "comparison")
        .prefetch_related(
            "bullet_list__items", "step_list__steps", "comparison__columns",
            "comparison__rows__cells",
        )
    )
    items = []
    for unit in units:
        relation = next(
            (relation for kind, _, relation in TYPE_ORDER if kind == unit.knowledge_type),
            None,
        )
        content = getattr(unit, relation, None) if relation else None
        if content is None:
            continue
        item = {
            "kind": unit.knowledge_type,
            "title": unit.title,
            "book": content.book_name.strip(),
            "chapter": content.chapter.strip(),
            "body": "",
            "details": [],
        }
        if unit.knowledge_type == KnowledgeUnit.KnowledgeType.DEFINITION:
            item["title"] = content.term or unit.title
            item["body"] = content.definition
        elif unit.knowledge_type == KnowledgeUnit.KnowledgeType.FORMULA:
            item["body"] = _formula_text(content.structure)
        elif unit.knowledge_type == KnowledgeUnit.KnowledgeType.BULLET_LIST:
            item["title"] = content.question or unit.title
            item["details"] = [
                (entry.text, entry.description) for entry in content.items.all()
            ]
        elif unit.knowledge_type == KnowledgeUnit.KnowledgeType.STEPS:
            item["title"] = content.question or unit.title
            item["details"] = [
                (entry.text, entry.description) for entry in content.steps.all()
            ]
        elif unit.knowledge_type == KnowledgeUnit.KnowledgeType.COMPARISON:
            item["title"] = content.name or unit.title
            columns = list(content.columns.all())
            item["details"] = [
                (
                    row.name or f"Row {row.order}",
                    "; ".join(
                        f"{column.name}: {cells.get(column.pk, '')}"
                        for column in columns if cells.get(column.pk)
                    ),
                )
                for row in content.rows.all()
                for cells in [{cell.column_id: cell.content for cell in row.cells.all()}]
            ]
        items.append(item)

    for note in Note.objects.filter(subject=subject):
        items.append({
            "kind": "NOTE", "title": note.title, "book": note.book_name.strip(),
            "chapter": note.chapter.strip(), "body": note.content, "details": [],
        })
    return items


def _styles():
    regular, bold = _font_names()
    ink = colors.HexColor("#263246")
    muted = colors.HexColor("#637286")
    green = colors.HexColor("#398729")
    return {
        "title": ParagraphStyle("Title", fontName=bold, fontSize=23, leading=30,
                                textColor=ink, spaceAfter=8),
        "subtitle": ParagraphStyle("Subtitle", fontName=regular, fontSize=9,
                                   leading=14, textColor=muted, spaceAfter=19),
        "book": ParagraphStyle("Book", fontName=bold, fontSize=16, leading=22,
                               textColor=ink, spaceBefore=20, spaceAfter=8,
                               keepWithNext=True),
        "chapter": ParagraphStyle("Chapter", fontName=bold, fontSize=12,
                                  leading=17, textColor=ink, spaceBefore=15,
                                  spaceAfter=7, keepWithNext=True),
        "type": ParagraphStyle("Type", fontName=bold, fontSize=10, leading=15,
                               textColor=green, spaceBefore=12, spaceAfter=7,
                               keepWithNext=True),
        "item": ParagraphStyle("Item", fontName=bold, fontSize=10, leading=15,
                               textColor=ink, spaceBefore=8, spaceAfter=5,
                               keepWithNext=True),
        "body": ParagraphStyle("Body", fontName=regular, fontSize=9,
                               leading=14.5, textColor=ink, spaceAfter=6),
        "detail": ParagraphStyle("Detail", fontName=regular, fontSize=8.5,
                                 leading=13.5, leftIndent=11, textColor=ink,
                                 spaceAfter=5),
        "empty": ParagraphStyle("Empty", fontName=regular, fontSize=10,
                                leading=16, textColor=muted, alignment=TA_CENTER,
                                spaceBefore=35),
    }


def _add_item(story, item, styles):
    story.append(Paragraph(_safe(item["title"]), styles["item"]))
    if item["body"]:
        story.append(Paragraph(_safe(item["body"]), styles["body"]))
    for index, (label, description) in enumerate(item["details"], start=1):
        prefix = f"{index}. " if item["kind"] == KnowledgeUnit.KnowledgeType.STEPS else "• "
        text = f"{prefix}{label}"
        if description:
            text += f" - {description}"
        story.append(Paragraph(_safe(text), styles["detail"]))
    story.append(Spacer(1, 4 * mm))


def _add_type_groups(story, items, styles):
    grouped = defaultdict(list)
    for item in items:
        grouped[item["kind"]].append(item)
    for kind, heading, _ in TYPE_ORDER:
        if kind not in grouped:
            continue
        story.append(Paragraph(heading, styles["type"]))
        for item in sorted(grouped[kind], key=lambda entry: entry["title"].casefold()):
            _add_item(story, item, styles)


def _build_pdf(subject, mode, items):
    stream = io.BytesIO()
    regular, bold = _font_names()
    styles = _styles()
    doc = SimpleDocTemplate(
        stream, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=28 * mm, bottomMargin=21 * mm,
        title=f"{subject.name} - Study summary", author="StudiGarden",
    )
    story = [
        Paragraph(_safe(subject.name), styles["title"]),
        Paragraph(
            f"Study summary  |  {'Regular' if mode == 'regular' else 'Books & chapters'}"
            f"  |  {timezone.localdate():%d %B %Y}", styles["subtitle"],
        ),
        HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#58b82a")),
        Spacer(1, 4 * mm),
    ]
    if not items:
        story.append(Paragraph("No saved study material for this subject yet.", styles["empty"]))
    elif mode == "regular":
        _add_type_groups(story, items, styles)
    else:
        books, extra = _group_by_book_and_chapter(items)
        for book in sorted(books, key=_natural_sort_key):
            story.append(Paragraph(_safe(book), styles["book"]))
            for chapter in sorted(books[book], key=_natural_sort_key):
                story.append(Paragraph(_safe(chapter), styles["chapter"]))
                _add_type_groups(story, books[book][chapter], styles)
        if extra:
            story.append(Paragraph("Extra", styles["book"]))
            _add_type_groups(story, extra, styles)

    def decorate(canvas, document):
        canvas.saveState()
        width, height = A4
        canvas.setFont(bold, 8)
        canvas.setFillColor(colors.HexColor("#398729"))
        canvas.drawString(20 * mm, height - 16 * mm, "STUDIGARDEN")
        canvas.setStrokeColor(colors.HexColor("#dce5db"))
        canvas.line(20 * mm, height - 19 * mm, width - 20 * mm, height - 19 * mm)
        canvas.setFont(regular, 8)
        canvas.setFillColor(colors.HexColor("#637286"))
        canvas.drawString(20 * mm, 13 * mm, subject.name[:65])
        canvas.drawRightString(width - 20 * mm, 13 * mm, str(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return stream.getvalue()


def _group_by_book_and_chapter(items):
    books = defaultdict(lambda: defaultdict(list))
    extra = []
    for item in items:
        if item["book"] and item["chapter"]:
            books[item["book"]][item["chapter"]].append(item)
        else:
            extra.append(item)
    return books, extra


@login_required
@require_GET
def download_subject_summary(request, subject_id):
    mode = request.GET.get("organize", "regular")
    if mode not in {"regular", "books"}:
        return HttpResponseBadRequest("Invalid summary organization.")
    subject = get_object_or_404(Subject, pk=subject_id, user=request.user)
    pdf = _build_pdf(subject, mode, _collect_items(subject))
    response = HttpResponse(pdf, content_type="application/pdf")
    name = slugify(subject.name)[:60] or "subject"
    response["Content-Disposition"] = (
        f'attachment; filename="studigarden-{name}-summary.pdf"'
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response

"""Conservative suggestions for the four structured learning-item types.

The scanner uses visible document signals - list markers, sequential numbering,
note labels and aligned table columns - rather than treating ordinary prose as
structured study material. Every result remains a draft for human review.
"""

import re


LIST_HEADING = re.compile(
    r"^(?:(?:assumptions?|key points?|main points?|requirements?|advantages?|"
    r"disadvantages?|causes?|limitations?|properties|criteria)\b.{0,75}|"
    r".{0,75}\b(?:effects?|checklists?|types|approaches)\b|.+\bmust)\s*:?$",
    re.I,
)
STEPS_HEADING = re.compile(
    r"^(?:worked (?:method|procedure|example)|(?:method|procedure|steps) (?:for|to|of)|how to)\b.{0,70}$",
    re.I,
)
COMPARISON_HEADING = re.compile(
    r"^(?:comparison of .+|.{3,75} compared|.{3,75} versus .{3,75})$",
    re.I,
)
NOTE_INLINE = re.compile(
    r"^(Study note|Note|Important|TL;?DR|Interpretation|Exam trap)\s*[.:]\s*(.+)$",
    re.I,
)
NOTE_HEADING = re.compile(
    r"^(?:the chapter in one sentence|core relationship|exam shortcut|"
    r"most to least accurate|best conclusion|calculation discipline|"
    r"decision rule|key judg(?:e)?ment|remember|warning)$",
    re.I,
)
FORMULA_TOPIC = re.compile(r"^\d{1,2}\.\s+(.{2,120})$")
NUMBERED_STEP = re.compile(r"^(\d{1,2})[.)]?\s+(.+)$")
ONLY_NUMBER = re.compile(r"^(\d{1,2})[.)]?$", re.I)
BULLET_ITEM = re.compile(r"^[\u2022\u25cf*\ufffd]\s*(.+)$")
CONTENTS = re.compile(r"^(?:table of )?contents$", re.I)
PAGE_FURNITURE = re.compile(
    r"^(?:page\s+\d+|exam study guide|.*\blearning unit\s+\d+.*)$", re.I,
)
TABLE_FIRST_COLUMNS = {
    "feature", "criterion", "criteria", "type", "component", "approach",
    "decision", "investment", "measure",
}
MAX_ITEMS = 20


def _clean(line):
    return " ".join((line or "").replace("\u00ad", "").split()).strip()


def _is_contents_page(lines):
    cleaned = [_clean(line) for line in lines[:35]]
    return any(CONTENTS.fullmatch(line) for line in cleaned)


def _is_furniture(line):
    return bool(PAGE_FURNITURE.fullmatch(_clean(line)))


def _is_boundary(line):
    line = _clean(line)
    return bool(
        STEPS_HEADING.fullmatch(line)
        or COMPARISON_HEADING.fullmatch(line)
        or LIST_HEADING.fullmatch(line)
        or NOTE_INLINE.match(line)
        or NOTE_HEADING.fullmatch(line)
        or line.upper().startswith("CHAPTER ")
    )


def _candidate(title, page, **fields):
    return {"title": title[:255], "page": page, "confidence": "possible", **fields}


def _entry(text):
    text = _clean(text)
    if ":" in text:
        label, detail = text.split(":", 1)
        if 1 < len(label) <= 120 and detail.strip():
            return {"text": label.strip()[:255], "description": detail.strip()[:500]}
    return {"text": text[:255], "description": text[255:755].strip()}


def _marker(raw):
    line = _clean(raw)
    bullet = BULLET_ITEM.fullmatch(line)
    if bullet:
        return None, bullet.group(1)
    numbered = NUMBERED_STEP.fullmatch(line)
    if numbered:
        return int(numbered.group(1)), numbered.group(2)
    return None


def _collect_list_entries(lines, start):
    entries, current = [], ""
    expected_number = None
    for raw in lines[start + 1:]:
        line = _clean(raw)
        if not line or _is_furniture(line):
            continue
        marked = _marker(raw)
        if marked:
            number, text = marked
            if number is not None:
                if expected_number is None:
                    expected_number = number
                if number != expected_number:
                    break
                expected_number += 1
            if current:
                entries.append(_entry(current))
            current = text
            if len(entries) >= MAX_ITEMS:
                break
            continue
        if _is_boundary(line) or ONLY_NUMBER.fullmatch(line):
            break
        if not current:
            continue
        if current.rstrip().endswith((".", "!", "?", ";")):
            break
        current += " " + line
    if current and len(entries) < MAX_ITEMS:
        entries.append(_entry(current))
    return entries


def _collect_plain_list_entries(lines, start):
    """Fallback for clean PDFs that omit bullet glyphs during extraction."""
    entries, pending = [], []
    for raw in lines[start + 1:]:
        line = _clean(raw)
        if not line or _is_furniture(line):
            continue
        if _is_boundary(line) or ONLY_NUMBER.fullmatch(line) or _marker(raw):
            break
        pending.append(line)
        joined = " ".join(pending)
        if joined.endswith((".", "!", "?", ";")):
            entries.append(_entry(joined))
            pending = []
        if len(entries) >= MAX_ITEMS:
            break
    return entries


def find_list_candidates(page_text, page_number):
    """Find visibly marked lists under a list-like heading."""
    lines = (page_text or "").splitlines()
    if _is_contents_page(lines):
        return []
    found = []
    for start, raw in enumerate(lines):
        title = _strip_section_number(_clean(raw)).rstrip(":")
        if not LIST_HEADING.fullmatch(_clean(raw)):
            continue
        items = _collect_list_entries(lines, start)
        if len(items) < 2:
            items = _collect_plain_list_entries(lines, start)
        if 2 <= len(items) <= MAX_ITEMS:
            found.append(_candidate(title, page_number, items=items))
    return found


def _collect_numbered_steps(lines, start):
    steps = []
    current = None
    expected = None
    continuation_lines = 0
    index = start
    while index < len(lines):
        line = _clean(lines[index])
        index += 1
        if not line or _is_furniture(line):
            continue
        match = NUMBERED_STEP.fullmatch(line)
        if match is None:
            only = ONLY_NUMBER.fullmatch(line)
            if only and index < len(lines):
                following = _clean(lines[index])
                if following and not _is_boundary(following):
                    number, title = int(only.group(1)), following
                    index += 1
                else:
                    break
            else:
                if current is None or _is_boundary(line):
                    break
                continuation_lines += 1
                if continuation_lines > 3:
                    break
                current["description"] = (
                    (current["description"] + " " + line).strip()
                )[:500]
                continue
        else:
            number, title = int(match.group(1)), match.group(2)
        if expected is None:
            expected = number
        if number != expected or len(title) > 255:
            break
        if current is not None:
            steps.append(current)
        current = {"text": title, "description": ""}
        expected += 1
        continuation_lines = 0
        if len(steps) >= MAX_ITEMS:
            break
    if current is not None and len(steps) < MAX_ITEMS:
        steps.append(current)
    return steps


def _strip_section_number(title):
    return re.sub(r"^\d+(?:\.\d+)*[.)]?\s+", "", title).rstrip(":")


def find_step_candidates(page_text, page_number):
    """Find numbered procedures while rejecting contents and formula banks."""
    lines = (page_text or "").splitlines()
    if _is_contents_page(lines):
        return []
    found, used_starts = [], set()
    for heading_index, raw in enumerate(lines):
        title = _clean(raw)
        if not title or LIST_HEADING.fullmatch(title):
            continue
        next_index = heading_index + 1
        while next_index < len(lines) and not _clean(lines[next_index]):
            next_index += 1
        if next_index >= len(lines):
            continue
        first = NUMBERED_STEP.fullmatch(_clean(lines[next_index]))
        explicit = bool(STEPS_HEADING.fullmatch(title))
        if first is None or int(first.group(1)) != 1:
            continue
        previous = next(
            (_clean(value) for value in reversed(lines[:heading_index]) if _clean(value) and not _is_furniture(value)),
            "",
        )
        if previous and LIST_HEADING.fullmatch(previous):
            continue
        steps = _collect_numbered_steps(lines, next_index)
        minimum = 2 if explicit else 3
        if len(steps) >= minimum:
            found.append(_candidate(_strip_section_number(title), page_number, steps=steps))
            used_starts.add(next_index)

    # A numbered sequence can continue at the top of the following PDF page.
    for index, raw in enumerate(lines):
        if index in used_starts:
            continue
        match = NUMBERED_STEP.fullmatch(_clean(raw))
        if match is None or int(match.group(1)) <= 1:
            continue
        prior = [_clean(value) for value in lines[:index] if _clean(value) and not _is_furniture(value)]
        if prior:
            continue
        steps = _collect_numbered_steps(lines, index)
        if len(steps) >= 2:
            item = _candidate("Continued steps", page_number, steps=steps)
            item["_continuation_start"] = int(match.group(1))
            found.append(item)
        break
    return found


def _note_body(lines, start, initial=""):
    content = [initial] if initial else []
    began = bool(initial)
    for raw in lines[start:]:
        line = _clean(raw)
        if not line:
            if began:
                break
            continue
        if _is_furniture(line):
            continue
        if _is_boundary(line) or FORMULA_TOPIC.fullmatch(line):
            break
        began = True
        content.append(line)
        if sum(len(part) for part in content) > 3000:
            break
    return " ".join(content).strip()[:3000]


def find_note_candidates(page_text, page_number):
    """Find labelled callouts and group formula guidance into useful notes."""
    lines = (page_text or "").splitlines()
    if _is_contents_page(lines):
        return []
    found = []
    current_topic = ""
    grouped = {}
    for index, raw in enumerate(lines):
        line = _clean(raw)
        topic = FORMULA_TOPIC.fullmatch(line)
        if topic:
            current_topic = topic.group(1).strip()
            continue
        inline = NOTE_INLINE.match(line)
        if inline:
            label = inline.group(1).replace(";", ":")
            body = _note_body(lines, index + 1, inline.group(2))
            if len(body) < 20:
                continue
            if current_topic and label.casefold() in {"tl:dr", "tldr", "interpretation", "exam trap"}:
                grouped.setdefault(current_topic, []).append(f"{label}: {body}")
            else:
                found.append(_candidate(label.capitalize(), page_number, content=body))
            continue
        if NOTE_HEADING.fullmatch(line):
            body = _note_body(lines, index + 1)
            if 20 <= len(body) <= 3000:
                found.append(_candidate(line, page_number, content=body))
    for topic, parts in grouped.items():
        found.append(_candidate(f"{topic} notes", page_number, content="\n\n".join(parts)))
    return found


def _segments(raw):
    return [
        (match.start(), _clean(match.group()))
        for match in re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|$)", raw.rstrip())
    ]


def _table_title(lines, header_index, first_column):
    for raw in reversed(lines[max(0, header_index - 6):header_index]):
        title = _clean(raw)
        if COMPARISON_HEADING.fullmatch(title):
            return title
    return f"{first_column.capitalize()} comparison"


def _table_candidate(lines, header_index, page_number):
    header_segments = _segments(lines[header_index])
    if len(header_segments) != 3:
        return None
    header = [text for _, text in header_segments]
    if header[0].casefold() not in TABLE_FIRST_COLUMNS:
        return None
    starts = [position for position, _ in header_segments]
    rows = []
    current = None
    for raw in lines[header_index + 1:]:
        if not raw.strip() or _is_furniture(raw):
            continue
        line = _clean(raw)
        if _is_boundary(line):
            break
        parts = _segments(raw)
        left = _clean(raw[starts[0]:starts[1]])
        middle = _clean(raw[starts[1]:starts[2]])
        right = _clean(raw[starts[2]:])
        if left and len(parts) >= 2 and (middle or right):
            if current:
                rows.append(current)
            current = {"name": left[:255], "cells": [middle, right]}
            if len(rows) >= MAX_ITEMS:
                break
            continue
        if current and not left and (middle or right):
            if middle:
                current["cells"][0] = (current["cells"][0] + " " + middle).strip()[:2000]
            if right:
                current["cells"][1] = (current["cells"][1] + " " + right).strip()[:2000]
            continue
        if current:
            break
    if current and len(rows) < MAX_ITEMS:
        rows.append(current)
    rows = [row for row in rows if row["name"] and all(row["cells"])]
    if len(rows) < 2:
        return None
    return _candidate(
        _table_title(lines, header_index, header[0]), page_number,
        columns=header[1:], rows=rows,
    )


def _paired_comparison(lines, heading_index, page_number):
    pairs, current = [], None
    for raw in lines[heading_index + 1:]:
        line = _clean(raw)
        if not line or _is_furniture(line):
            continue
        if _is_boundary(line):
            break
        bullet = BULLET_ITEM.fullmatch(line)
        if bullet and ":" in bullet.group(1):
            if current:
                pairs.append(current)
            name, body = bullet.group(1).split(":", 1)
            current = [name.strip(), body.strip()]
            if len(pairs) >= 2:
                break
            continue
        if current and not _is_boundary(line) and not current[1].endswith((".", "!", "?")):
            current[1] += " " + line
            continue
        if current:
            break
    if current and len(pairs) < 2:
        pairs.append(current)
    if len(pairs) != 2 or any(not name or not body for name, body in pairs):
        return None
    return _candidate(
        _clean(lines[heading_index]), page_number,
        columns=[pairs[0][0][:255], pairs[1][0][:255]],
        rows=[{"name": "Explanation", "cells": [pairs[0][1][:2000], pairs[1][1][:2000]]}],
    )


def find_comparison_candidates(layout_text, page_number):
    """Find aligned three-column tables and paired 'versus' explanations."""
    lines = (layout_text or "").splitlines()
    if _is_contents_page(lines):
        return []
    found = []
    for index in range(len(lines)):
        table = _table_candidate(lines, index, page_number)
        if table:
            found.append(table)
        if COMPARISON_HEADING.fullmatch(_clean(lines[index])):
            paired = _paired_comparison(lines, index, page_number)
            if paired:
                found.append(paired)
    unique = []
    seen = set()
    for item in found:
        key = (item["title"].casefold(), tuple(name.casefold() for name in item["columns"]))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique

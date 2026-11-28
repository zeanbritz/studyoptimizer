"""Conservative suggestions for the four structured learning-item types.

The scanner uses visible document signals - list markers, sequential numbering,
note labels and aligned table columns - rather than treating ordinary prose as
structured study material. Every result remains a draft for human review.
"""

import re
from bisect import bisect_right
from itertools import combinations

from .pdf_text import (
    CALLOUT, FURNITURE, ORDINAL, QUESTION, SECTION, bullet_text,
    clean as _clean, is_non_instructional_page, segments as _segments, short_heading,
)


LIST_HEADING = re.compile(
    r"^(?:(?:assumptions?|key points?|main points?|requirements?|advantages?|"
    r"disadvantages?|causes?|limitations?|properties|criteria)\b.{0,75}|"
    r".{0,75}\b(?:effects?|checklists?|types|approaches)\b|.+\bmust)\s*:?$",
    re.I,
)
STEPS_HEADING = re.compile(
    r"^(?:worked (?:method|procedure|example)|(?:method|procedure|steps) (?:for|to|of|in)|how to)\b.{0,70}$",
    re.I,
)
COMPARISON_HEADING = re.compile(
    r"^(?:comparison of .+|.{3,75} compared|.{3,75} (?:versus|vs\.?) .{3,75})$",
    re.I,
)
ONLY_NUMBER = re.compile(r"^(\d{1,2})[.)]?$", re.I)
ACTION = re.compile(
    r"^(?:add|adjust|analy[sz]e|apply|assess|calculate|check|choose|collect|compare|compute|"
    r"confirm|create|decide|define|determine|divide|estimate|evaluate|find|formulate|gather|"
    r"identify|interpret|list|measure|monitor|multiply|record|research|review|select|"
    r"specify|subtract|sum|test|use|verify|weigh)\b", re.I,
)
SUBHEADING = re.compile(
    r"^(?:strengths|weaknesses|characteristics|market implications|objectives|uses?|"
    r"examples?|risks|tracks|advantages|disadvantages|limitations|benefits|"
    r"best-performing assets|challenges|mainly|during (?:a |an |the )?\w+)$", re.I,
)
INTERPRETIVE = re.compile(
    r"^(?:therefore,|what matters is|these reduce|trend growth serves as|"
    r".{3,90}\b(?:therefore tend to|form the foundation|is intended to be|"
    r"is typically linked to|is most useful for|depends on whether|result from)\b)", re.I,
)
TABLE_FIRST_COLUMNS = {
    "feature", "criterion", "criteria", "type", "component", "approach",
    "decision", "investment", "measure", "variable", "metric", "asset class",
}
STEP_TABLE_FIRST_COLUMNS = {
    "step", "steps", "step number", "step no", "number", "numbered step", "no",
}
MAX_ITEMS = 20


def _is_furniture(line):
    return bool(FURNITURE.fullmatch(_clean(line)))


def _is_boundary(line):
    line = _clean(line)
    return bool(
        _is_furniture(line) or SECTION.fullmatch(line) or QUESTION.fullmatch(line)
        or STEPS_HEADING.fullmatch(line) or COMPARISON_HEADING.fullmatch(line)
        or CALLOUT.fullmatch(line)
        or SUBHEADING.fullmatch(line.rstrip(":")) or line.endswith(":")
        or line.upper().startswith("CHAPTER ")
    )


def _is_question_page(lines):
    first = [_clean(line) for line in lines if line.strip()][:5]
    return (
        any(re.fullmatch(r"activity\s+\d+", line, re.I) for line in first)
        and not any(re.search(r"\bsolutions?\b", line, re.I) for line in first)
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
    bullet = bullet_text(line)
    if bullet:
        return None, bullet
    numbered = ORDINAL.fullmatch(line)
    if numbered:
        return int(numbered.group(2)), numbered.group(3)
    return None


def _collect_plain_list_entries(lines, start):
    """Fallback for clean PDFs that omit bullet glyphs during extraction."""
    entries, pending = [], []
    for raw in lines[start + 1:]:
        line = _clean(raw)
        if not line or _is_furniture(line):
            continue
        if _is_boundary(line) or _marker(raw):
            break
        pending.append(line)
        joined = " ".join(pending)
        if joined.endswith((".", "!", "?", ";")):
            entries.append(_entry(joined))
            pending = []
        if len(entries) >= MAX_ITEMS:
            break
    return entries


def _list_runs(lines):
    """Read contiguous, visually marked groups without absorbing the next heading."""
    index = 0
    while index < len(lines):
        start = index
        marker = _marker(lines[index])
        if not marker or len(_segments(lines[index])) >= 2 and _clean(lines[index]).count("\u2022") > 1:
            index += 1
            continue
        first_number = marker[0]
        indent = len(lines[index]) - len(lines[index].lstrip())
        entries = []
        while marker and marker[0] == (
            None if first_number is None else first_number + len(entries)
        ) and abs(len(lines[index]) - len(lines[index].lstrip()) - indent) <= 3:
            text = marker[1]
            if entries and short_heading(text) and index + 1 < len(lines):
                next_line = next(
                    (_clean(raw).rstrip(":") for raw in lines[index + 1:] if raw.strip()), ""
                )
                if text.istitle() and next_line.casefold() in {"example", "examples"}:
                    break
            index += 1
            while index < len(lines) and lines[index].strip() and not _marker(lines[index]):
                continuation = _clean(lines[index])
                if (
                    _is_boundary(continuation) or text.endswith((".", "!", "?", ";"))
                    or not continuation[0].islower()
                    or len(_segments(lines[index])) > 2
                ):
                    break
                text += " " + continuation
                index += 1
            entries.append(text)
            if index < len(lines) and not lines[index].strip():
                next_index = index
                while next_index < len(lines) and not lines[next_index].strip():
                    next_index += 1
                if next_index < len(lines) and _marker(lines[next_index]):
                    index = next_index
            marker = _marker(lines[index]) if index < len(lines) else None
        yield start, [entry for entry in entries if not entry.endswith(":")], first_number


def _list_context(lines, start):
    """Get the nearest visible group label, subtopic and section in reading order."""
    preceding = [raw for raw in lines[:start] if raw.strip()]
    if not preceding:
        return "", "", ""
    last = preceding[-1]
    label = _clean(last).rstrip(":")
    parts = _segments(last)
    if len(parts) == 2:
        lead = re.fullmatch(r"of (?:various|different|several) (.+) such as:", parts[-1][1], re.I)
        if lead:
            label = lead.group(1).capitalize()
    section, topic = "", ""
    for index, raw in enumerate(preceding[:-1]):
        next_raw = preceding[index + 1]
        line, following = _clean(raw), _clean(next_raw)
        same_margin = len(raw) - len(raw.lstrip()) <= len(next_raw) - len(next_raw.lstrip()) + 3
        number = SECTION.fullmatch(line)
        subnumber = re.match(r"^\d+\s*\.\s*\d", line)
        if number and not subnumber and (not _marker(following) or not section):
            if SUBHEADING.fullmatch(following.rstrip(":")) and section:
                topic = number.group(1)
            else:
                section, topic = number.group(1), ""
        elif number and subnumber:
            topic = number.group(1)
        elif (
            same_margin and short_heading(line) and not _is_boundary(line) and not _marker(line)
            and SUBHEADING.fullmatch(following.rstrip(":"))
        ):
            topic = line
    label_section = SECTION.fullmatch(_clean(last))
    if label_section:
        return label_section.group(1), "", ""
    if len(preceding) >= 2:
        latest_topic = bullet_text(_clean(preceding[-2]))
        if latest_topic and latest_topic.istitle() and short_heading(latest_topic) and label.casefold() in {"example", "examples"}:
            topic = latest_topic
    return section, topic, label


def _sequence_is_procedure(entries, heading, *, explicit_labels=False):
    title = _strip_section_number(heading)
    if re.match(r"^how to use (?:this|the) (?:pdf|guide|document|book|chapter|manual)", title, re.I):
        return False
    if explicit_labels or STEPS_HEADING.fullmatch(title):
        return len(entries) >= 2
    return (
        len(entries) >= 3 and not LIST_HEADING.fullmatch(title)
        and all(ACTION.match(entry) for entry in entries)
    )


def _indented_list(lines, heading_index):
    raw = lines[heading_index]
    if not raw.strip().endswith(":") or not short_heading(_clean(raw)):
        return []
    indent = len(raw) - len(raw.lstrip())
    entries = []
    for raw in lines[heading_index + 1:]:
        text = _clean(raw)
        if not text or len(raw) - len(raw.lstrip()) < indent + 4:
            break
        if _marker(raw) or _is_boundary(text) or "=" in text:
            return []
        entries.append(text)
    return entries


def find_list_candidates(page_text, page_number):
    """Use each marked list's local heading and preserve enclosing subtopics."""
    lines = (page_text or "").splitlines()
    if is_non_instructional_page(lines) or _is_question_page(lines):
        return []
    found = []
    runs = list(_list_runs(lines))
    runs.extend(
        (index + 1, entries, None)
        for index in range(len(lines))
        if len(entries := _indented_list(lines, index)) >= 2
    )
    for start, entries, number in sorted(runs):
        section, topic, label = _list_context(lines, start)
        if (
            len(entries) < 2 or label and _is_furniture(label)
            or number is not None and _sequence_is_procedure(entries, label)
        ):
            continue
        if number is not None and (number != 1 or any(_step_table_header(line) for line in lines[:start])):
            continue
        previous_bullet = bullet_text(label)
        if previous_bullet and next(
            (raw.rstrip() for raw in reversed(lines[:start]) if raw.strip()), ""
        ).endswith(":"):
            label = previous_bullet
        elif label.endswith((".", "!", "?", ";")) or _marker(label):
            label = ""
        if CALLOUT.fullmatch(label):
            continue
        label = _strip_section_number(label)
        parent = topic or section
        title = f"{parent} \u2014 {label}" if parent and label and parent != label else (label or parent)
        if not title or label and "=" in label:
            continue
        item = _candidate(title, page_number, items=[_entry(entry) for entry in entries[:MAX_ITEMS]])
        if section and label.casefold().startswith("during "):
            item["_comparison_group"] = (section, label, "Response")
        elif section and topic and label and SUBHEADING.fullmatch(label):
            item["_comparison_group"] = (section, topic, label)
        found.append(item)

    for index, raw in enumerate(lines):
        if not LIST_HEADING.fullmatch(_clean(raw)):
            continue
        items = _collect_plain_list_entries(lines, index)
        if len(items) >= 2:
            found.append(_candidate(_strip_section_number(_clean(raw)), page_number, items=items))
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
        match = ORDINAL.fullmatch(line)
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
            number, title = int(match.group(2)), match.group(3)
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


def _table_header_key(value):
    return re.sub(r"[^a-z]+", " ", _clean(value).casefold()).strip()


def _step_table_header(raw):
    """Return aligned header columns only for an explicitly numbered step table."""
    segments = _segments(raw)
    if len(segments) < 2:
        return None
    if _table_header_key(segments[0][1]) not in STEP_TABLE_FIRST_COLUMNS:
        return None
    return segments


def _step_table_title(lines, header_index):
    """Prefer the section name printed above a table, never its column labels."""
    for raw in reversed(lines[max(0, header_index - 6):header_index]):
        title = _strip_section_number(_clean(raw)).rstrip(":")
        if not title or _is_furniture(title) or _step_table_header(raw):
            continue
        if STEPS_HEADING.fullmatch(title):
            return title[:255]
        if _is_boundary(title) or ORDINAL.fullmatch(title):
            break
        if title.endswith((".", "!", "?")) or len(title.split()) > 18:
            continue
        return title[:255]
    return "Steps"


def _table_step_candidate(lines, header_index, page_number):
    """Turn a numbered Step/Action table into one editable steps suggestion."""
    header = _step_table_header(lines[header_index])
    if not header:
        return None
    starts = [position for position, _ in header]
    second_start = starts[1]
    third_start = starts[2] if len(starts) > 2 else None
    delimiter = "\t" if "\t" in lines[header_index] else "|" if "|" in lines[header_index] else ""
    steps, current = [], None
    expected = 1

    for raw in lines[header_index + 1:]:
        line = _clean(raw)
        if not line or _is_furniture(line):
            continue
        if _is_boundary(line) and not ORDINAL.fullmatch(line):
            break

        if delimiter:
            cells = [_clean(cell) for cell in raw.split(delimiter)]
            number_cell = cells[0] if cells else ""
            action = cells[1] if len(cells) > 1 else ""
            detail = " ".join(cell for cell in cells[2:] if cell)
        else:
            number_cell = _clean(raw[:second_start])
            action = _clean(
                raw[second_start:third_start] if third_start is not None else raw[second_start:]
            )
            detail = _clean(raw[third_start:]) if third_start is not None else ""
        number = ONLY_NUMBER.fullmatch(number_cell)
        if number:
            if int(number.group(1)) != expected or not action:
                break
            if current:
                steps.append(current)
            current = {"text": action[:255], "description": detail[:500]}
            expected += 1
            if len(steps) >= MAX_ITEMS:
                break
            continue

        # A continuation should stay beneath the action columns. A line that
        # starts in the number column marks the end of this compact table.
        if current and not number_cell and (action or detail):
            continuation = " ".join(part for part in (action, detail) if part)
            current["description"] = (
                f"{current['description']} {continuation}".strip()
            )[:500]
            continue
        break

    if current and len(steps) < MAX_ITEMS:
        steps.append(current)
    if len(steps) < 2:
        return None
    return _candidate(
        _step_table_title(lines, header_index), page_number, steps=steps,
    )


def find_step_candidates(page_text, page_number):
    """Keep actionable sequences and step tables apart from numbered lists."""
    lines = (page_text or "").splitlines()
    if is_non_instructional_page(lines) or _is_question_page(lines):
        return []
    found = []
    for index, raw in enumerate(lines):
        if _step_table_header(raw):
            table = _table_step_candidate(lines, index, page_number)
            if table:
                found.append(table)

    for index, raw in enumerate(lines):
        first = ORDINAL.fullmatch(_clean(raw))
        if first is None:
            continue
        number = int(first.group(2))
        previous = [_clean(line) for line in lines[:index] if line.strip() and not _is_furniture(line)]
        if number > 1 and previous:
            continue
        steps = _collect_numbered_steps(lines, index)
        if number > 1:
            if len(steps) >= 2 and all(ACTION.match(step["text"]) for step in steps):
                found.append(_candidate(
                    "Continued steps", page_number, steps=steps, _continuation_start=number,
                ))
            continue
        title = next(
            (
                QUESTION.fullmatch(line).group(1) if QUESTION.fullmatch(line) else _strip_section_number(line)
                for line in reversed(previous)
                if (
                    STEPS_HEADING.fullmatch(_strip_section_number(line))
                    or short_heading(line) and not QUESTION.fullmatch(line)
                    or QUESTION.fullmatch(line) and QUESTION.fullmatch(line).group(1)
                ) and not CALLOUT.fullmatch(line)
            ),
            "Worked procedure",
        )
        if found and any(_step_table_header(line) for line in lines[:index]):
            continue
        if title == "Worked procedure" or title.casefold().startswith("using "):
            title = steps[-1]["text"] if steps else title
        if _sequence_is_procedure(
            [step["text"] for step in steps], title, explicit_labels=bool(first.group(1)),
        ):
            found.append(_candidate(title, page_number, steps=steps))
    return found


def _note_body(lines, start, initial=""):
    content = [initial] if initial else []
    for raw in lines[start:]:
        line = _clean(raw)
        if not line:
            if content:
                break
            continue
        if _is_boundary(line) and not (not content and line.endswith(":") and not CALLOUT.fullmatch(line)):
            break
        if (
            content and line[0].isupper() and short_heading(line)
            and not bullet_text(line) and not content[-1].endswith(("→", ","))
        ):
            break
        content.append(line)
        if sum(len(part) for part in content) > 3000:
            break
    return " ".join(content).strip()[:3000]


def find_note_candidates(page_text, page_number):
    """Keep contextual callouts and explicit interpretations as notes."""
    lines = (page_text or "").splitlines()
    if is_non_instructional_page(lines) or _is_question_page(lines):
        return []
    found = []
    current_topic, local_topic = "", ""
    grouped = {}
    previous = ""
    for index, raw in enumerate(lines):
        line = _clean(raw)
        if not line:
            continue
        context, previous = previous, line
        topic = SECTION.fullmatch(line)
        if topic:
            current_topic, local_topic = topic.group(1), ""
            continue
        match = CALLOUT.fullmatch(line)
        if match:
            label = match.group("label").replace(";", ":")
            body = _note_body(lines, index + 1, match.group("body") or "")
            if len(body) < 20:
                continue
            if current_topic and label.casefold() in {"tl:dr", "tldr", "interpretation", "exam trap"}:
                grouped.setdefault(current_topic, []).append(f"{label}: {body}")
            else:
                context = local_topic if label.casefold() == "implication" else current_topic
                title = f"{context} \u2014 {label}" if context else label.capitalize()
                found.append(_candidate(title, page_number, content=body))
        elif INTERPRETIVE.match(bullet_text(line) or line) and not CALLOUT.fullmatch(context):
            content = _note_body(lines, index + 1, bullet_text(line) or line)
            if len(content) >= 20:
                title = local_topic or current_topic or "Takeaway"
                found.append(_candidate(title, page_number, content=content))
        elif short_heading(line) and not _is_boundary(line) and not ORDINAL.fullmatch(line):
            local_topic = line
    for topic, parts in grouped.items():
        found.append(_candidate(f"{topic} notes", page_number, content="\n\n".join(parts)))
    return found


def _table_title(lines, header_index, first_column):
    for raw in reversed(lines[max(0, header_index - 6):header_index]):
        title = _clean(raw)
        question = QUESTION.fullmatch(title)
        if question and question.group(1):
            return question.group(1)
        if COMPARISON_HEADING.fullmatch(title):
            return title
    return f"{first_column.capitalize()} comparison" if first_column else "Comparison"


def _comparison_cells(raw, starts):
    """Split at visible column starts, tolerating slight layout rounding."""
    parts = _segments(raw)
    cells = [""] * (len(starts) + 1)
    for position, value in parts:
        index = bisect_right(starts, position + 2)
        cells[index] = " ".join(filter(None, (cells[index], value)))
    return cells


def _table_candidate(lines, header_index, page_number):
    header_segments = _segments(lines[header_index])
    if any(bullet_text(part) or part.endswith(")") and "(" not in part for _, part in header_segments):
        return None
    if len(header_segments) == 3:
        first_column, *headers = [text for _, text in header_segments]
        if _table_header_key(first_column) not in TABLE_FIRST_COLUMNS:
            return None
        starts = [position for position, _ in header_segments[1:]]
    elif len(header_segments) == 2:
        # A matrix can leave the row-header column blank. Require the two
        # column titles to be indented above real row labels.
        starts = [position for position, _ in header_segments]
        if starts[0] < 5 or starts[1] - starts[0] < 12:
            return None
        first_column = ""
        headers = [text for _, text in header_segments]
    else:
        return None

    rows, current = [], None
    header_wrapped = False
    for raw in lines[header_index + 1:]:
        if not raw.strip():
            if current:
                break
            continue
        left, middle, right = _comparison_cells(raw, starts)
        if (left and _is_boundary(left) and not (middle or right)) or _step_table_header(raw):
            break
        if left and (middle or right):
            if current and all(current["cells"]):
                rows.append(current)
                if len(rows) >= MAX_ITEMS:
                    current = None
                    break
            current = {"name": left[:255], "cells": [middle[:2000], right[:2000]]}
        elif not left and (middle or right):
            if current:
                for index, segment in enumerate((middle, right)):
                    if segment:
                        current["cells"][index] = f"{current['cells'][index]} {segment}".strip()[:2000]
            elif not rows and middle and right and not bullet_text(middle) and not bullet_text(right):
                headers = [f"{name} {tail}" for name, tail in zip(headers, (middle, right))]
                header_wrapped = True
            else:
                break
        else:
            break
    if current and all(current["cells"]) and len(rows) < MAX_ITEMS:
        rows.append(current)
    if len(rows) < 2:
        return None
    if not first_column and not header_wrapped and not all(
        SUBHEADING.fullmatch(row["name"].rstrip(":")) for row in rows
    ):
        return None
    return _candidate(
        _table_title(lines, header_index, first_column), page_number,
        columns=[header[:255] for header in headers], rows=rows,
    )


def group_comparisons(lists):
    """Compare parallel groups under the same section, including across pages."""
    sections = {}
    for item in lists:
        context = item.pop("_comparison_group", None)
        if not context:
            continue
        section, topic, label = context
        groups = sections.setdefault(section, {})
        groups.setdefault(topic, {})[label] = item

    for section, topics in sections.items():
        pairs = (
            zip(topics.items(), list(topics.items())[1:])
            if len(topics) > 3 else combinations(topics.items(), 2)
        )
        for (left, first), (right, second) in pairs:
            labels = [label for label in first if label in second]
            if not labels:
                continue
            rows = []
            for label in labels:
                cells = [
                    "\n".join(
                        f"\u2022 {entry['text']}: {entry['description']}" if entry["description"]
                        else f"\u2022 {entry['text']}" for entry in side[label]["items"]
                    )[:2000] for side in (first, second)
                ]
                rows.append({"name": label[:255], "cells": cells})
            items = [side[label] for side in (first, second) for label in labels]
            yield _candidate(
                f"{section}: {left} vs {right}", min(item["page"] for item in items),
                columns=[left[:255], right[:255]], rows=rows,
                **({"source": "image"} if any(item.get("source") == "image" for item in items) else {}),
            )


def _paired_comparison(lines, heading_index, page_number):
    pairs, current = [], None
    for raw in lines[heading_index + 1:]:
        line = _clean(raw)
        if not line or _is_furniture(line):
            continue
        if _is_boundary(line):
            break
        bullet = bullet_text(line)
        if bullet and ":" in bullet:
            if current:
                pairs.append(current)
            name, body = bullet.split(":", 1)
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


def _outcome_comparisons(lines, header_index, page_number):
    """A labelled outcome table compares what happens to each entity."""
    header = _segments(lines[header_index])
    if len(header) != 2 or _table_header_key(header[0][1]) not in TABLE_FIRST_COLUMNS:
        return []
    position, outcome = header[1]
    if not re.match(r"^(?:implications?|outcomes?|responses?|effects?)\b", outcome, re.I):
        return []
    values = {}
    last = ""
    for raw in lines[header_index + 1:]:
        if not raw.strip():
            continue
        label, value = _comparison_cells(raw, (position,))
        if not label and value and last:
            values[last] = f"{values[last]} {value}"[:2000]
            continue
        if not label or not value or _is_boundary(label):
            break
        last = label[:255]
        values[last] = value[:2000]
        if len(values) == MAX_ITEMS:
            break
    title = _table_title(lines, header_index, header[0][1])
    return [
        _candidate(
            f"{title}: {left} vs {right}", page_number, columns=[left, right],
            rows=[{"name": outcome[:255], "cells": [values[left], values[right]]}],
        )
        for left, right in zip(values, list(values)[1:])
    ]


def find_comparison_candidates(layout_text, page_number):
    """Find aligned three-column tables and paired 'versus' explanations."""
    lines = (layout_text or "").splitlines()
    if is_non_instructional_page(lines) or _is_question_page(lines):
        return []
    found = []
    for index in range(len(lines)):
        table = _table_candidate(lines, index, page_number)
        if table:
            found.append(table)
        found.extend(_outcome_comparisons(lines, index, page_number))
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

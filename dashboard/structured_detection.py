"""Conservative suggestions for the four structured learning-item types.

These rules intentionally require recognizable headings and layout. A PDF scan
is a draft for human review, not a claim that arbitrary textbook prose has
been classified correctly.
"""

import re


LIST_HEADING = re.compile(
    r"^(?:assumptions(?: to check)?|key points|main points|requirements|"
    r"advantages|disadvantages|causes|effects|checklist)(?:\s+.{0,55})?$",
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
NOTE_START = re.compile(r"^(Study note|Note|Important)\s*[.:]\s*(.+)$", re.I)
NUMBERED_STEP = re.compile(r"^(\d{1,2})[.)]?\s+(.+)$")
ONLY_NUMBER = re.compile(r"^(\d{1,2})[.)]?$", re.I)
MAX_ITEMS = 20


def _clean(line):
    return " ".join(line.split()).strip()


def _is_boundary(line):
    line = _clean(line)
    return bool(
        STEPS_HEADING.fullmatch(line)
        or COMPARISON_HEADING.fullmatch(line)
        or LIST_HEADING.fullmatch(line)
        or NOTE_START.match(line)
        or line.upper().startswith("CHAPTER ")
    )


def _candidate(title, page, **fields):
    return {"title": title[:255], "page": page, "confidence": "possible", **fields}


def find_list_candidates(page_text, page_number):
    """Find short groups following an explicit list-like heading."""
    lines = (page_text or "").splitlines()
    found = []
    for start, raw in enumerate(lines):
        title = _clean(raw)
        if not LIST_HEADING.fullmatch(title):
            continue
        items, pending = [], []
        for next_raw in lines[start + 1:]:
            line = _clean(next_raw)
            if not line:
                continue
            if _is_boundary(line) or ONLY_NUMBER.fullmatch(line):
                break
            pending.append(line)
            joined = " ".join(pending)
            if joined.endswith((".", "!", "?", ";")):
                if len(joined) <= 255:
                    items.append({"text": joined, "description": ""})
                pending = []
            if len(items) >= MAX_ITEMS:
                break
        if 2 <= len(items) <= MAX_ITEMS:
            found.append(_candidate(title, page_number, items=items))
    return found


def find_step_candidates(page_text, page_number):
    """Find explicitly numbered methods, preserving each step's explanation."""
    lines = (page_text or "").splitlines()
    found = []
    for start, raw in enumerate(lines):
        title = _clean(raw)
        if not STEPS_HEADING.fullmatch(title):
            continue
        steps = []
        index = start + 1
        while index < len(lines):
            line = _clean(lines[index])
            if not line:
                index += 1
                continue
            if _is_boundary(line):
                break
            match = NUMBERED_STEP.fullmatch(line)
            if match is None:
                only = ONLY_NUMBER.fullmatch(line)
                if only and index + 1 < len(lines):
                    following = _clean(lines[index + 1])
                    if following and not _is_boundary(following):
                        match_number, step_title = int(only.group(1)), following
                        index += 1
                    else:
                        break
                else:
                    if steps and len(steps[-1]["description"]) < 500:
                        steps[-1]["description"] = (
                            (steps[-1]["description"] + " " + line).strip()
                        )[:500]
                    index += 1
                    continue
            else:
                match_number, step_title = int(match.group(1)), match.group(2)
            if match_number != len(steps) + 1 or len(step_title) > 255:
                break
            steps.append({"text": step_title, "description": ""})
            if len(steps) >= MAX_ITEMS:
                break
            index += 1
        if len(steps) >= 2:
            found.append(_candidate(title, page_number, steps=steps))
    return found


def find_note_candidates(page_text, page_number):
    """Find text explicitly marked as a study note."""
    lines = (page_text or "").splitlines()
    found = []
    for start, raw in enumerate(lines):
        match = NOTE_START.match(_clean(raw))
        if not match:
            continue
        title = match.group(1).capitalize()
        content = [match.group(2)]
        for next_raw in lines[start + 1:]:
            line = _clean(next_raw)
            if not line or _is_boundary(line):
                break
            content.append(line)
            if sum(len(part) for part in content) > 3000:
                break
        body = " ".join(content).strip()
        if 20 <= len(body) <= 3000:
            found.append(_candidate(title, page_number, content=body))
    return found


def find_comparison_candidates(layout_text, page_number):
    """Find simple three-field rows: feature + exactly two compared columns."""
    lines = (layout_text or "").splitlines()
    found = []
    for start, raw in enumerate(lines):
        title = _clean(raw)
        if not COMPARISON_HEADING.fullmatch(title):
            continue
        nonempty = [line for line in lines[start + 1:] if line.strip()]
        if not nonempty:
            continue
        header = re.split(r"\s{2,}", nonempty[0].strip())
        if len(header) != 3 or header[0].casefold() not in {"feature", "criterion", "criteria"}:
            continue
        columns = [_clean(name) for name in header[1:]]
        if any(not name or len(name) > 255 for name in columns):
            continue
        rows = []
        for raw_row in nonempty[1:]:
            if _is_boundary(raw_row):
                break
            cells = re.split(r"\s{2,}", raw_row.strip())
            if len(cells) != 3:
                break
            name, left, right = map(_clean, cells)
            if not all((name, left, right)) or len(name) > 255 or len(left) > 2000 or len(right) > 2000:
                break
            rows.append({"name": name, "cells": [left, right]})
            if len(rows) >= MAX_ITEMS:
                break
        if rows:
            found.append(_candidate(title, page_number, columns=columns, rows=rows))
    return found

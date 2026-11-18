"""Conservative, review-only definition candidates from selectable PDF text."""

import re


LABEL = re.compile(r"^definition(?:\s+\d+(?:\.\d+)*)?\s*[:.\-]?\s*(.*)$", re.I)
COLON = re.compile(r"^(?P<term>.{2,85}?)\s*:\s*(?P<body>.{15,})$")
DASH = re.compile(r"^(?P<term>.{2,85}?)\s+[\u2013\u2014-]\s+(?P<body>.{15,})$")
SENTENCE = re.compile(
    r"^(?P<term>[A-Z][\w'()/-]*(?:\s+[\w'()/-]+){0,5}?)\s+"
    r"(?P<link>is|are|means|refers\s+to)\s+(?P<body>.{20,})$"
)
SECTION = re.compile(r"^(definitions|glossary|key terms|key vocabulary)\s*:?$", re.I)
OTHER_SECTION = re.compile(
    r"^(chapter\b|exercises?\b|review questions?\b|references\b|bibliography\b)",
    re.I,
)
EXCLUDED_TERMS = re.compile(
    r"^(?:example|exercise|chapter|figure|table|page|summary|note|tip|"
    r"question|answer|learning outcome|the|this|these|those|it|we|they|when|a|an|"
    r"tl;?dr|interpretation|exam trap|first pass|second pass|third pass|final pass|"
    r"return not)\b",
    re.I,
)
CONTENTS = re.compile(r"^(?:table of )?contents$", re.I)
NOTE_CONTEXT = re.compile(
    r"^(?:the chapter in one sentence|core relationship|exam shortcut|"
    r"most to least accurate|best conclusion|calculation discipline|"
    r"decision rule|key judg(?:e)?ment|remember|warning)$",
    re.I,
)
TABLE_TERM_HEADERS = {
    "term", "terms", "key term", "key terms", "concept", "concepts",
    "word", "words", "vocabulary", "terminology",
}
TABLE_MEANING_HEADERS = {
    "meaning", "meanings", "definition", "definitions", "description",
    "descriptions", "explanation", "explanations", "what it means",
}
MAX_TABLE_ROWS = 40


def _clean(line):
    line = line.replace("\u00ad", "").replace("\ufb01", "fi").replace("\ufb02", "fl")
    line = re.sub(r"^[\u2022\u25cf*]\s*", "", line)
    return re.sub(r"\s+", " ", line).strip()


def _header_key(value):
    """Normalise a short table heading without changing its visible content."""
    return re.sub(r"[^a-z]+", " ", _clean(value).casefold()).strip()


def _column_segments(raw):
    """Return visible columns from pypdf's layout-preserving text output."""
    if "|" in raw:
        pieces = []
        position = 0
        for piece in raw.split("|"):
            cleaned = _clean(piece)
            if cleaned:
                leading_space = len(piece) - len(piece.lstrip())
                pieces.append((position + leading_space, cleaned))
            position += len(piece) + 1
        return pieces
    return [
        (match.start(), _clean(match.group()))
        for match in re.finditer(r"\S(?:.*?\S)?(?=(?: {2,}|\t+)|$)", raw.rstrip())
    ]


def _definition_table_header(raw):
    segments = _column_segments(raw)
    if len(segments) != 2:
        return None
    headers = [_header_key(value) for _, value in segments]
    if (
        headers[0] not in TABLE_TERM_HEADERS
        or headers[1] not in TABLE_MEANING_HEADERS
    ):
        return None
    return segments


def _table_definition_candidates(lines, page_number):
    """Read explicit Term/Meaning tables without guessing at ordinary prose."""
    found = []
    for header_index, raw in enumerate(lines):
        header = _definition_table_header(raw)
        if not header:
            continue

        second_column_start = header[1][0]
        delimiter = "\t" if "\t" in raw else "|" if "|" in raw else ""
        current = None
        rows = []
        for row_raw in lines[header_index + 1:]:
            line = _clean(row_raw)
            if not line:
                continue
            if SECTION.match(line) or OTHER_SECTION.match(line):
                break

            if delimiter:
                cells = row_raw.split(delimiter, 1)
                term = _clean(cells[0])
                meaning = _clean(cells[1]) if len(cells) == 2 else ""
            else:
                term = _clean(row_raw[:second_column_start])
                meaning = _clean(row_raw[second_column_start:])
            if term and meaning and _valid_term(term):
                if current:
                    rows.append(current)
                current = {"term": term, "definition": meaning}
                if len(rows) >= MAX_TABLE_ROWS:
                    break
                continue

            # Long meanings sometimes wrap beneath their own column. Keep only
            # a clearly indented continuation, never a new prose paragraph.
            if current and not term and meaning:
                combined = f"{current['definition']} {meaning}".strip()
                if len(combined) <= 1200:
                    current["definition"] = combined
                    continue
            break

        if current and len(rows) < MAX_TABLE_ROWS:
            rows.append(current)
        valid_rows = [
            row for row in rows
            if _valid_term(row["term"]) and _valid_definition(row["definition"])
        ]
        # Two valid rows make it clear this is a genuine glossary-style table,
        # rather than a one-off two-column layout elsewhere in the document.
        if len(valid_rows) >= 2:
            found.extend({
                "term": row["term"],
                "definition": row["definition"],
                "page": page_number,
                "confidence": "strong",
            } for row in valid_rows)
    return found


def _valid_term(term):
    term = term.strip(" .:-\u2013\u2014")
    return bool(
        2 <= len(term) <= 85
        and len(term.split()) <= 8
        and any(char.isalpha() for char in term)
        and not EXCLUDED_TERMS.match(term)
        and not re.search(r"[.!?]", term)
        and not re.search(r"[=<>±×÷^_]", term)
    )


def _valid_definition(body):
    return len(body) >= 20 and len(body.split()) >= 4 and len(body) <= 1200


def _split_entry(line):
    for pattern in (COLON, DASH):
        match = pattern.match(line)
        if match and _valid_term(match.group("term")):
            return match.group("term"), match.group("body"), pattern is COLON
    return None


def _extend_body(body, lines, start):
    """Join a few visual lines only when a definition has not ended yet."""
    consumed = 0
    while consumed < 3 and start + consumed < len(lines):
        line = lines[start + consumed]
        if not line or body.rstrip().endswith((".", "!", "?")):
            break
        if LABEL.match(line) or SECTION.match(line) or _split_entry(line):
            break
        if len(body) + len(line) > 1200:
            break
        body += " " + line
        consumed += 1
    return body, consumed


def find_definition_candidates(page_text, page_number):
    """Return candidates, never authoritative definitions or database writes."""
    lines = [_clean(line) for line in (page_text or "").splitlines()]
    if any(CONTENTS.fullmatch(line) for line in lines[:30]):
        return []
    candidates = _table_definition_candidates(
        (page_text or "").splitlines(), page_number
    )
    seen = {
        (candidate["term"].casefold(), candidate["definition"].casefold())
        for candidate in candidates
    }

    def add_candidate(candidate):
        key = (candidate["term"].casefold(), candidate["definition"].casefold())
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)
    in_glossary = False
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line:
            continue
        if SECTION.match(line):
            in_glossary = True
            continue
        if OTHER_SECTION.match(line):
            in_glossary = False
            continue

        labelled = LABEL.match(line)
        if labelled:
            line = labelled.group(1).strip()
            if not line and index < len(lines):
                line = lines[index]
                index += 1

        entry = _split_entry(line)
        if entry:
            term, body, colon = entry
            body, consumed = _extend_body(body, lines, index)
            index += consumed
            if _valid_definition(body):
                add_candidate({
                    "term": term, "definition": body, "page": page_number,
                    "confidence": "strong" if labelled or colon else "possible",
                })
            continue

        if (labelled or in_glossary) and _valid_term(line):
            next_index = index
            while next_index < len(lines) and not lines[next_index]:
                next_index += 1
            if next_index < len(lines):
                body, consumed = _extend_body(lines[next_index], lines, next_index + 1)
                if _valid_definition(body) and not _split_entry(lines[next_index]):
                    add_candidate({
                        "term": line, "definition": body, "page": page_number,
                        "confidence": "strong" if labelled else "possible",
                    })
                    index = next_index + 1 + consumed
                    continue

        sentence = SENTENCE.match(line)
        if sentence and _valid_term(sentence.group("term")):
            body, consumed = _extend_body(line, lines, index)
            previous = next((value for value in reversed(lines[:index - 1]) if value), "")
            if (
                not NOTE_CONTEXT.fullmatch(previous)
                and body.endswith((".", "!", "?"))
                and _valid_definition(sentence.group("body"))
            ):
                add_candidate({
                    "term": sentence.group("term"), "definition": body,
                    "page": page_number, "confidence": "possible",
                })
                index += consumed

    return candidates

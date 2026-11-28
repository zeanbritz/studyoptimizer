"""Conservative, review-only definition candidates from selectable PDF text."""

import re

from .pdf_text import (
    CALLOUT, METADATA, ORDINAL, bullet_text, is_non_instructional_page, segments, short_heading,
)


LABEL = re.compile(r"^definition(?:\s+\d+(?:\.\d+)*)?\s*[:.\-]?\s*(.*)$", re.I)
COLON = re.compile(r"^(?P<term>.{2,85}?)\s*:\s*(?P<body>.{15,})$")
DASH = re.compile(r"^(?P<term>.{2,85}?)\s+[\u2013\u2014-]\s+(?P<body>.{15,})$")
SENTENCE = re.compile(
    r"^(?P<term>[A-Z][\w'()/-]*(?:\s+[\w'()/-]+){0,5}?)\s+"
    r"(?P<link>is|are|means|refers\s+to|describes|measures)\s+(?P<body>.+)$"
)
SECTION = re.compile(r"^(definitions|glossary|key terms|key vocabulary)\s*:?$", re.I)
OTHER_SECTION = re.compile(
    r"^(chapter\b|exercises?\b|review questions?\b|references\b|bibliography\b)",
    re.I,
)
EXCLUDED_TERMS = re.compile(
    r"^(?:example|exercise|chapter|figure|table|page|summary|note|tip|"
    r"question|answer|learning outcome|the|this|these|those|it|we|they|when|a|an|"
    r"presenter|date|instructor|what matters|implication|step|exam (?:tip|point)|"
    r"tl;?dr|interpretation|exam trap|first pass|second pass|third pass|final pass|"
    r"return not)\b",
    re.I,
)
DEFINITION_PREDICATE = re.compile(
    r"^(?:the (?:process|movement|change|speed|amount|rate|time|value|measure|tendency|"
    r"difference|ratio|total|sum|weighted|method|practice|ability|fraction|price|"
    r"degree|return|result|distance|attractive|portion|risk|spread)|a|an|"
    r"(?:(?:economic|statistical) )?forecasts?|expectations|estimates|"
    r"defined as|calculated as|used to measure)\b", re.I,
)
GLOSS = re.compile(r"^(?:a |an |the |relying |preferring |seeking |overestimating |"
                   r"being |overweighting |compensation |consistency )", re.I)
TOPIC_LABEL = re.compile(r"^(?:characteristics|strengths|weaknesses|examples|uses|"
                         r"tracks|formula|summary|objectives|challenges|benefits|"
                         r"advantages|limitations|market implications|risks)$", re.I)
INLINE_CONTEXT = re.compile(r"^(?:what (?:is|are)|how does|why is)\b", re.I)
PARENTHETICAL_GLOSS = re.compile(r"^([^()]{3,80})\s+\(([^()]{10,})\)\s*[.]?$")
LIST_DEFINITION = re.compile(
    r"^(.{3,80}?)\s+(includes?|consists? of|is made up of|helps? evaluate)\s*:$",
    re.I,
)
NAMING = re.compile(r"^(?:this|that)(?: is| are) (?:known|called|referred to)(?: as)? (.+?)[.]?$", re.I)
GLOSS_CLAUSE = re.compile(
    r"^(?:compensation|the ability|the risk|the likelihood|"
    r"a[n]? (?:currency|measure|method|process|value|rate|ratio))\b", re.I,
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
    line = line.strip().replace("\u00ad", "").replace("\ufb01", "fi").replace("\ufb02", "fl")
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
        and not TOPIC_LABEL.fullmatch(term)
        and not CALLOUT.fullmatch(term)
        and not re.fullmatch(r'[A-Z]{2,8}\s*\d{2,8}', term)
        and not re.search(r"[.!?]", term)
        and not re.search(r"[=<>±×÷^_]", term)
    )


def _valid_definition(body):
    return (
        12 <= len(body) <= 1200
        and len(body.split()) >= 3
        and not re.search(r"[=→]", body)
        and not METADATA.match(body)
    )


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
        if (
            LABEL.match(line) or SECTION.match(line) or _split_entry(line)
            or CALLOUT.fullmatch(line) or ORDINAL.fullmatch(line)
            or bullet_text(line) or METADATA.match(line)
            or (line[0].isupper() and short_heading(line))
        ):
            break
        if len(body) + len(line) > 1200:
            break
        body += " " + line
        consumed += 1
    return body, consumed


def find_definition_candidates(page_text, page_number):
    """Return candidates, never authoritative definitions or database writes."""
    raw_lines = (page_text or "").splitlines()
    if is_non_instructional_page(raw_lines):
        return []
    candidates = _table_definition_candidates(raw_lines, page_number)
    seen = {candidate["term"].casefold() for candidate in candidates}
    lines = [(" ".join(raw.split()), _clean(raw)) for raw in raw_lines]
    in_glossary = False
    previous = ""
    group_entries = []

    def add(term, body, confidence="possible"):
        if _valid_term(term) and _valid_definition(body) and term.casefold() not in seen:
            seen.add(term.casefold())
            candidates.append({
                "term": term, "definition": body, "page": page_number, "confidence": confidence,
            })

    index = 0
    while index < len(lines):
        marked, line = lines[index]
        index += 1
        if not line:
            continue
        context, previous = previous, line
        if not bullet_text(marked) and not NAMING.fullmatch(line):
            group_entries.clear()
        elif bullet_text(marked):
            group_entries.append(line.rstrip("."))
        naming = NAMING.fullmatch(line)
        if naming and 2 <= len(group_entries) <= 8:
            # Use the visible lead-in, including constraints such as "cannot".
            for raw, lead in reversed(lines[:index - 1]):
                if lead and not bullet_text(raw):
                    if lead.endswith(":"):
                        definition = f"{lead[:-1]} {', '.join(group_entries)}."
                        add(re.sub(r"^the\s+", "", naming.group(1), flags=re.I), definition)
                    break
            continue
        if SECTION.fullmatch(line):
            in_glossary = True
            continue
        if OTHER_SECTION.match(line):
            in_glossary = False
            continue
        if CALLOUT.fullmatch(line) or METADATA.match(line) or ORDINAL.fullmatch(line):
            continue

        labelled = LABEL.match(line)
        if labelled:
            line = labelled.group(1).strip() or next(
                (value for _, value in lines[index:] if value), ""
            )
            if not labelled.group(1).strip():
                while index < len(lines) and lines[index][1] != line:
                    index += 1
                index += 1

        remaining = [raw for raw, _ in lines[index:index + 4]]
        entry = _split_entry(line)
        if entry:
            term, body, colon = entry
            body, consumed = _extend_body(body, remaining, 0)
            if _valid_definition(body):
                add(term, body, "strong" if labelled or colon else "possible")
                index += consumed
            continue

        following = next((i for i in range(index, len(lines)) if lines[i][1]), None)
        if (labelled or in_glossary) and _valid_term(line) and following is not None:
            tail = [raw for raw, _ in lines[following + 1:following + 4]]
            body, consumed = _extend_body(lines[following][1], tail, 0)
            if _valid_definition(body) and not _split_entry(lines[following][1]):
                add(line, body, "strong" if labelled else "possible")
                index = following + 1 + consumed
                continue

        gloss = PARENTHETICAL_GLOSS.fullmatch(line) if bullet_text(marked) else None
        if gloss and GLOSS.match(gloss.group(2)):
            add(gloss.group(1).strip(), gloss.group(2))
            continue

        composition = LIST_DEFINITION.fullmatch(line)
        tracks = re.fullmatch(r"tracks\s*:", line, re.I) and short_heading(context)
        if composition or tracks:
            term, relation = composition.groups() if composition else (context, "tracks")
            term = re.sub(r"^the\s+", "", term, flags=re.I)
            entries = []
            for raw, value in lines[index:index + 10]:
                if not value:
                    continue
                if not bullet_text(raw) or value[-1] == ":":
                    break
                if entries and short_heading(value) and not value.endswith("."):
                    break
                entries.append(value.rstrip("."))
            if len(entries) >= 2:
                add(term, f"{term} {relation} {'; '.join(entries)}.")
            continue

        sentence = SENTENCE.match(line)
        if sentence and (
            sentence.group("link") not in {"is", "are"}
            or DEFINITION_PREDICATE.match(sentence.group("body"))
        ):
            if CALLOUT.fullmatch(context) or sentence.group("body").endswith(":") and not (
                INLINE_CONTEXT.match(context) or "forecast" in sentence.group("body").casefold()
            ):
                continue
            body, consumed = _extend_body(line, remaining, 0)
            if sentence.group("body").endswith(":"):
                entries, qualifier = [], ""
                for offset in range(index, min(index + 8, len(lines))):
                    item = bullet_text(lines[offset][0])
                    if not lines[offset][1]:
                        continue
                    if not item:
                        column = segments(raw_lines[offset])[-1][1]
                        if entries and column.startswith("of ") and column.endswith(" such as:"):
                            qualifier = " " + column.removesuffix(" such as:")
                        break
                    entries.append(item.rstrip("."))
                if entries:
                    lead = re.sub(r"\bthe:$", "", line, flags=re.I).rstrip(": ")
                    body = lead + " " + ", ".join(entries) + qualifier + "."
            add(sentence.group("term").strip(), body)
            index += consumed
            continue

        if (
            short_heading(context) and not CALLOUT.fullmatch(context)
            and not _split_entry(context) and GLOSS.match(line)
            and (GLOSS_CLAUSE.match(line) or bullet_text(marked))
        ):
            body, consumed = _extend_body(line, remaining, 0)
            add(context.removesuffix(":"), body)
            index += consumed

    return candidates

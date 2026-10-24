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


def _clean(line):
    line = line.replace("\u00ad", "").replace("\ufb01", "fi").replace("\ufb02", "fl")
    line = re.sub(r"^[\u2022\u25cf*]\s*", "", line)
    return re.sub(r"\s+", " ", line).strip()


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
    candidates = []
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
                candidates.append({
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
                    candidates.append({
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
                candidates.append({
                    "term": sentence.group("term"), "definition": body,
                    "page": page_number, "confidence": "possible",
                })
                index += consumed

    return candidates

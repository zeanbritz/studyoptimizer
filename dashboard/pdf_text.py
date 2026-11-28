"""Shared text and layout signals used by the PDF study detectors."""

import re


BULLET = re.compile(r"^[\u2022\u25cf\u25aa\u25e6\u2023\u25a0\ufffd*]\s*(.+)$|^[-\u2013]\s+(.+)$")
ORDINAL = re.compile(r"^(?:(step)\s+)?(\d{1,2})(?:[.):]\s*|\s+)(.+)$", re.I)
SECTION = re.compile(r"^\d{1,2}(?:\s*\.\s*\d{1,2})*\s*\.\s+\.?\s*([A-Z].*?)\s*(?<![.!?])$")
QUESTION = re.compile(r"^questions?\s*(?:\d+|[a-z]\b)(?:\s*[:.\-]\s*(.+))?$", re.I)
METADATA = re.compile(
    r"^(?:presenter|lecturer|author|instructor|date|student name|module code|course code)\s*:",
    re.I,
)
CALLOUT = re.compile(
    r"^(?P<label>study note|key idea|key takeaway|important exam (?:point|tip)|exam (?:tip|point|trap|shortcut)|"
    r"important|implication|note|warning|remember|interpretation|TL;?DR|"
    r"the chapter in one sentence|core relationship|most to least accurate|best conclusion|"
    r"calculation discipline|decision rule|key judg(?:e)?ment)\b\s*(?:[.:]\s*(?P<body>.+)|[.:]?)$",
    re.I,
)
FURNITURE = re.compile(
    r"^(?:page\s+\d+|exam study guide|learning unit\s+\d+|activity\s+\d+|"
    r"(?:worked )?solutions?|thank you[!. ]*)$", re.I,
)


def clean(line):
    return " ".join(line.replace("\u00ad", "").replace("\ufb01", "fi").replace("\ufb02", "fl").split())


def segments(raw):
    """Locate the text runs of an aligned row without losing their columns."""
    return [
        (match.start(), clean(match.group()))
        for match in re.finditer(r"\S(?:.*?\S)?(?=(?: {2,}|\t+)|$)", raw.rstrip())
    ]


def bullet_text(line):
    match = BULLET.fullmatch(line)
    return (match.group(1) or match.group(2)) if match else ""


def is_non_instructional_page(lines):
    first = [clean(line) for line in lines if line.strip()][:12]
    if not first:
        return True
    if any(re.fullmatch(r"(?:table of )?contents", line, re.I) for line in first):
        return True
    return bool(
        len(first) <= 6 and any(METADATA.match(line) for line in first)
        and (
            sum(bool(METADATA.match(line)) for line in first) >= 2
            or re.match(r"^[A-Z]{2,8}\s*\d{2,8}\s*:", first[0])
        )
    )


def short_heading(line):
    """Identify short labels, while keeping full sentences out of headings."""
    return bool(
        line and len(line) <= 110 and len(line.split()) <= 13
        and line[0].isalpha() and not line.endswith((".", "?", "!", ";", ","))
        and not re.search(r"[=<>]", line)
        and not bullet_text(line)
    )

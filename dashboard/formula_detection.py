"""Conservative formula suggestions from selectable PDF text.

The editable structure preserves multi-word quantities and mathematical symbols.
"""

import re
from uuid import uuid4

from .pdf_text import bullet_text, is_non_instructional_page


COMMA_LINKED_VARIABLE = r"[^\W\d][\w]*(?:\s*,\s*[^\W\d][\w]*)+"
TOKEN = re.compile(
    rf"\d+(?:\.\d+)?|{COMMA_LINKED_VARIABLE}|[^\W\d][\w]*|[=+\-*/^()|<>{{}}\[\]$%~≠]",
    re.UNICODE,
)
PASTE_TOKEN = re.compile(
    rf"\d+(?:\.\d+)?|{COMMA_LINKED_VARIABLE}|[^\W\d][\w]*|[=+\-*/^()|<>{{}}\[\]$%~≠]",
    re.UNICODE,
)
FUNCTIONS = {"exp", "ln", "log", "sin", "cos", "tan", "sqrt"}
HEADING = re.compile(r"^[A-Z][A-Z ]{2,39}$")
PROSE_MARKER = re.compile(r"\b(?:where|because|which|when|therefore|is|are)\b", re.I)
SPACED_FUNCTION_LHS = re.compile(r"^[^\W\d][\w]*\([^()]*\)$", re.UNICODE)
# A quantity name such as "Expected Equity Return" must stay one editor part.
QUANTITY = re.compile(
    r"(?:[^\W\d]\w*|[A-Z]+/[A-Z]+)"
    r"(?:\s+(?:[^\W\d]\w*|[A-Z]+/[A-Z]+)){1,7}$"
)
QUANTITY_CONNECTORS = {"in", "of", "per", "to", "for", "on", "and"}
QUANTITY_STOP_WORDS = {
    "a", "an", "the", "has", "have", "had", "will", "should", "was", "were",
    "includes", "depends", "relies", "therefore", "since", "based", "please", "using", "we", "you",
}
NAMED_OR_MATH_TERM = r"[\w/ ]{2,50}"
VERBAL_EQUALITY = re.compile(
    rf"^({NAMED_OR_MATH_TERM}?)\s+must equal\s+({NAMED_OR_MATH_TERM})[.]?$",
    re.I,
)
NUMERIC_WORKING = re.compile(r"^[\d\s.%$+*/()\-]+$")
SUPERSCRIPT_CHARACTERS = str.maketrans({
    "⁰": "^0", "¹": "^1", "²": "^2", "³": "^3", "⁴": "^4",
    "⁵": "^5", "⁶": "^6", "⁷": "^7", "⁸": "^8", "⁹": "^9",
    "⁺": "^+", "⁻": "^-",
})


def _normalise_equation(equation):
    return (
        equation.replace("−", "-").replace("–", "-")
        .replace("×", "*").replace("÷", "/").strip()
        .translate(SUPERSCRIPT_CHARACTERS)
    )


def _formula_element(value):
    value = re.sub(r"\s*,\s*", ",", value)
    if value in {"=", "+", "-", "*", "/", "^", "<", ">"}:
        kind = "operator"
    elif re.fullmatch(r"\d+(?:\.\d+)?", value):
        kind = "number"
    elif value in {"(", ")", "{", "}", "[", "]", "|", "$", "%", "~", "≠"} or value.casefold() in FUNCTIONS:
        kind = "symbol"
    else:
        kind = "variable"
    return {
        "id": uuid4().hex,
        "type": kind,
        "value": value,
        "meaning": "",
    }


def _is_quantity(text):
    words = text.casefold().split()
    return bool(
        len(text) <= 50 and QUANTITY.fullmatch(text) and any(len(word) > 1 for word in words)
        and not QUANTITY_STOP_WORDS.intersection(words)
        and words[0] not in QUANTITY_CONNECTORS and words[-1] not in QUANTITY_CONNECTORS
        and not PROSE_MARKER.search(text)
    )


def _equation_tokens(part):
    tokens = []
    # Leave compact letter/letter notation intact inside named quantities.
    for fragment in re.split(r"([+\-*^()|<>{}\[\]$%~≠]|(?<![A-Z])\/|\/(?![A-Z]))", part):
        fragment = " ".join(fragment.split())
        if not fragment:
            continue
        if _is_quantity(fragment):
            tokens.append(fragment)
            continue
        matches = TOKEN.findall(fragment)
        if (
            "".join(re.sub(r"\s*,\s*", ",", value) for value in matches)
            != re.sub(r"\s+", "", fragment)
            or (
                re.search(r"[^\W\d]\s+[^\W\d]", fragment)
                and not all(re.fullmatch(r"[^\W\d]\d*", value) for value in matches)
            )
        ):
            raise ValueError("This equation has symbols the formula editor cannot parse safely.")
        tokens.extend(matches)
    return tokens


def equation_to_structure(equation):
    """Return safe formula-editor tokens, or raise ValueError if ambiguous."""
    equation = _normalise_equation(equation)
    if len(equation) > 200 or equation.count("=") != 1:
        raise ValueError("This equation needs manual entry in the formula editor.")
    lhs, rhs = (part.strip() for part in equation.split("=", 1))
    compact_lhs = re.sub(r"\s+", "", lhs)
    named_lhs = _is_quantity(lhs)
    if (
        not lhs or not rhs
        or not any(char.isalpha() for char in lhs + rhs)
        or (not named_lhs and len(compact_lhs) > 24)
        or (re.search(r"\s", lhs) and not named_lhs and not SPACED_FUNCTION_LHS.fullmatch(compact_lhs))
        or PROSE_MARKER.search(lhs + " " + rhs)
    ):
        raise ValueError("This equation needs manual entry in the formula editor.")
    tokens = [*_equation_tokens(lhs), "=", *_equation_tokens(rhs)]
    if len(tokens) > 40 or any(len(value) > 50 for value in tokens):
        raise ValueError("This equation needs manual entry in the formula editor.")
    return [_formula_element(value) for value in tokens]


def pasted_equation_to_structure(equation):
    """Keep recognised parts of a pasted equation instead of rejecting all of it."""
    source = _normalise_equation(equation)
    partial = False

    if len(source) > 400:
        source = source[:400]
        partial = True

    # Explanatory text often follows an otherwise usable equation. Stop before
    # it so normal words do not become pretend variables in the builder.
    prose = PROSE_MARKER.search(source)
    if prose:
        source = source[:prose.start()].rstrip()
        partial = True

    first_equals = source.find("=")
    if first_equals >= 0:
        second_equals = source.find("=", first_equals + 1)
        if second_equals >= 0:
            source = source[:second_equals].rstrip()
            partial = True

    tokens = []
    last_end = 0
    for match in PASTE_TOKEN.finditer(source):
        if source[last_end:match.start()].strip():
            partial = True
        tokens.append(match.group())
        last_end = match.end()
        if len(tokens) >= 40:
            partial = True
            break
    if source[last_end:].strip():
        partial = True

    structure = [_formula_element(value) for value in tokens]
    count = len(structure)
    if not count:
        message = "No recognised formula parts were added. You can still build it manually."
    elif partial:
        message = (
            f"Added {count} recognised formula part{'s' if count != 1 else ''}; "
            "skipped the parts the builder cannot use."
        )
    else:
        message = f"Added {count} formula part{'s' if count != 1 else ''} to the builder."

    return {"structure": structure, "message": message, "partial": partial}


def find_formula_candidates(page_text, page_number):
    """Find editable formula suggestions; never write to the database."""
    lines = (page_text or "").splitlines()
    if is_non_instructional_page(lines):
        return []
    candidates = []
    heading = None
    step_title = ""
    for raw_line in lines:
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        if HEADING.fullmatch(line):
            heading = line.title()
            continue
        step = re.fullmatch(r"Step\s+\d+\s*[:.)-]?\s+(.+)", line, re.I)
        if step:
            step_title = step.group(1)
            continue
        line = bullet_text(line) or line
        equality = VERBAL_EQUALITY.fullmatch(line)
        if equality:
            line = f"{equality.group(1)} = {equality.group(2)}"
        segments = [part.strip().rstrip(".") for part in line.split(";")]
        equations = []
        ambiguous_group = False
        for segment in segments:
            parts = [part.strip() for part in _normalise_equation(segment).split("=")]
            if len(parts) > 2 and all(NUMERIC_WORKING.fullmatch(part) for part in parts[2:]):
                segment = f"{parts[0]} = {parts[1]}"
            if (parts[0] != "0" and NUMERIC_WORKING.fullmatch(parts[0])) or (
                len(parts) > 1 and NUMERIC_WORKING.fullmatch(parts[1])
                and (len(parts[0].split()) > 1 or re.search(r"[%/]", parts[0]))
            ):
                continue
            try:
                structure = equation_to_structure(segment)
            except ValueError:
                # A mixed worked-solution sentence is not a formula list.
                if len(segments) > 1:
                    ambiguous_group = True
                continue
            equations.append((segment, structure))
        if ambiguous_group or len(segments) > 1 and len(equations) != len(segments):
            continue
        for equation, structure in equations:
            lhs = equation.split("=", 1)[0].strip()
            title = f"{heading} ({lhs})" if heading else f"{lhs} equation"
            if step_title and re.search(r"\bexcluding\b", step_title, re.I):
                title = step_title
            candidates.append({
                "title": title[:255],
                "equation": equation,
                "structure": structure,
                "page": page_number,
                "confidence": "strong" if heading else "possible",
            })
    return candidates

"""Conservative formula suggestions from selectable PDF text.

Only short, single-equals equations are accepted. The result is a flat formula
editor structure; students can refine meanings, functions and fractions later.
"""

import re
from uuid import uuid4


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


def equation_to_structure(equation):
    """Return safe formula-editor tokens, or raise ValueError if ambiguous."""
    equation = _normalise_equation(equation)
    if len(equation) > 160 or equation.count("=") != 1:
        raise ValueError("This equation needs manual entry in the formula editor.")
    lhs, rhs = (part.strip() for part in equation.split("=", 1))
    compact_lhs = re.sub(r"\s+", "", lhs)
    if (
        not lhs
        or not rhs
        or len(compact_lhs) > 24
        or (
            re.search(r"\s", lhs)
            and not SPACED_FUNCTION_LHS.fullmatch(compact_lhs)
        )
    ):
        raise ValueError("This equation needs manual entry in the formula editor.")
    if not any(char.isalpha() for char in lhs + rhs):
        raise ValueError("This equation needs manual entry in the formula editor.")
    if re.search(r"\b(?:where|because|which|when|therefore|is|are)\b", rhs, re.I):
        raise ValueError("This equation includes prose and needs manual entry.")
    tokens = TOKEN.findall(equation)
    compact_tokens = "".join(
        re.sub(r"\s*,\s*", ",", value)
        for value in tokens
    )
    if len(tokens) > 40 or compact_tokens != re.sub(r"\s+", "", equation):
        raise ValueError("This equation has symbols the formula editor cannot parse safely.")

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
    candidates = []
    heading = None
    for raw_line in (page_text or "").splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        if HEADING.fullmatch(line):
            heading = line.title()
            continue
        segments = [part.strip().rstrip(".") for part in line.split(";")]
        equations = []
        ambiguous_group = False
        for segment in segments:
            try:
                structure = equation_to_structure(segment)
            except ValueError:
                # A mixed worked-solution sentence is not a formula list.
                if len(segments) > 1:
                    ambiguous_group = True
                continue
            equations.append((segment, structure))
        if ambiguous_group:
            continue
        for equation, structure in equations:
            lhs = equation.split("=", 1)[0].strip()
            title = f"{heading} ({lhs})" if heading else f"{lhs} equation"
            candidates.append({
                "title": title[:255],
                "equation": equation,
                "structure": structure,
                "page": page_number,
                "confidence": "strong" if heading else "possible",
            })
    return candidates

"""Conservative formula suggestions from selectable PDF text.

Only short, single-equals equations are accepted. The result is a flat formula
editor structure; students can refine meanings, functions and fractions later.
"""

import re
from uuid import uuid4


TOKEN = re.compile(r"\d+(?:\.\d+)?|[^\W\d][\w]*|[=+\-*/^()|<>]", re.UNICODE)
FUNCTIONS = {"exp", "ln", "log", "sin", "cos", "tan", "sqrt"}
HEADING = re.compile(r"^[A-Z][A-Z ]{2,39}$")


def equation_to_structure(equation):
    """Return safe formula-editor tokens, or raise ValueError if ambiguous."""
    equation = (
        equation.replace("−", "-").replace("–", "-")
        .replace("×", "*").replace("÷", "/").strip()
    )
    if len(equation) > 160 or equation.count("=") != 1:
        raise ValueError("This equation needs manual entry in the formula editor.")
    lhs, rhs = (part.strip() for part in equation.split("=", 1))
    if not lhs or not rhs or len(lhs) > 24 or re.search(r"\s", lhs):
        raise ValueError("This equation needs manual entry in the formula editor.")
    if not any(char.isalpha() for char in lhs + rhs):
        raise ValueError("This equation needs manual entry in the formula editor.")
    if re.search(r"\b(?:where|because|which|when|therefore|is|are)\b", rhs, re.I):
        raise ValueError("This equation includes prose and needs manual entry.")
    tokens = TOKEN.findall(equation)
    if len(tokens) > 40 or "".join(tokens) != re.sub(r"\s+", "", equation):
        raise ValueError("This equation has symbols the formula editor cannot parse safely.")

    structure = []
    for value in tokens:
        if value in {"=", "+", "-", "*", "/", "^", "<", ">"}:
            kind = "operator"
        elif re.fullmatch(r"\d+(?:\.\d+)?", value):
            kind = "number"
        elif value in {"(", ")", "|"} or value.casefold() in FUNCTIONS:
            kind = "symbol"
        else:
            kind = "variable"
        structure.append({
            "id": uuid4().hex,
            "type": kind,
            "value": value,
            "meaning": "",
        })
    return structure


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

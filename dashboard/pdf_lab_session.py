"""Session-backed, short-lived preview data for the private PDF learning lab."""

from uuid import uuid4
from time import time


SESSION_KEY = "pdf_definition_lab_scan"
MAX_AGE_SECONDS = 24 * 60 * 60
KIND_KEYS = {
    "definition": ("candidates", "saved"),
    "formula": ("formula_candidates", "saved_formulas"),
    "list": ("list_candidates", "saved_lists"),
    "steps": ("step_candidates", "saved_steps"),
    "note": ("note_candidates", "saved_notes"),
    "comparison": ("comparison_candidates", "saved_comparisons"),
}


def save_scan(request, subject_id, scan, file_name, book_name="", chapter=""):
    state = {
        "id": uuid4().hex,
        "created_at": int(time()),
        "subject_id": subject_id,
        "scan": scan,
        "file_name": file_name,
        "book_name": book_name,
        "chapter": chapter,
        "saved": {},
        "saved_formulas": {},
        "saved_lists": {},
        "saved_steps": {},
        "saved_notes": {},
        "saved_comparisons": {},
    }
    request.session[SESSION_KEY] = state
    return state


def get_scan(request, subject_id, scan_id=None):
    state = request.session.get(SESSION_KEY)
    if not isinstance(state, dict) or state.get("subject_id") != subject_id:
        return None
    created_at = state.get("created_at")
    if not isinstance(created_at, (int, float)) or time() - created_at > MAX_AGE_SECONDS:
        request.session.pop(SESSION_KEY, None)
        return None
    if scan_id is not None and state.get("id") != scan_id:
        return None
    scan = state.get("scan")
    if not isinstance(scan, dict) or not isinstance(scan.get("candidates"), list):
        return None
    return state


def get_candidate(request, subject_id, scan_id, index, kind="definition"):
    state = get_scan(request, subject_id, scan_id)
    if kind not in KIND_KEYS:
        return None
    key = KIND_KEYS[kind][0]
    try:
        index = int(index)
    except (TypeError, ValueError):
        return None
    candidates = state["scan"].get(key, []) if state is not None else []
    if index < 0 or index >= len(candidates):
        return None
    return candidates[index]


def mark_saved(request, subject_id, scan_id, index, item_id, kind="definition"):
    state = get_scan(request, subject_id, scan_id)
    if state is None or get_candidate(request, subject_id, scan_id, index, kind) is None:
        return False
    key = KIND_KEYS[kind][1]
    state.setdefault(key, {})[str(index)] = item_id
    request.session[SESSION_KEY] = state
    return True

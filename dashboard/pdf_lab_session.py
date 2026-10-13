"""Session-backed, short-lived preview data for the private PDF definition lab."""

from uuid import uuid4
from time import time


SESSION_KEY = "pdf_definition_lab_scan"
MAX_AGE_SECONDS = 24 * 60 * 60


def save_scan(request, subject_id, scan, file_name):
    state = {
        "id": uuid4().hex,
        "created_at": int(time()),
        "subject_id": subject_id,
        "scan": scan,
        "file_name": file_name,
        "saved": {},
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


def get_candidate(request, subject_id, scan_id, index):
    state = get_scan(request, subject_id, scan_id)
    try:
        index = int(index)
    except (TypeError, ValueError):
        return None
    if state is None or index < 0 or index >= len(state["scan"]["candidates"]):
        return None
    return state["scan"]["candidates"][index]


def mark_saved(request, subject_id, scan_id, index, definition_id):
    state = get_scan(request, subject_id, scan_id)
    if state is None or get_candidate(request, subject_id, scan_id, index) is None:
        return False
    state["saved"][str(index)] = definition_id
    request.session[SESSION_KEY] = state
    return True

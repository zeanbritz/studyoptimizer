"""Explicit, per-flow review origins. Never accept a return URL from a client."""

from functools import wraps
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.core import signing
from django.urls import Resolver404, resolve, reverse


ORIGINS = {"standard", "garden", "subject", "library"}
REVIEW_ROUTES = {
    "definition_review_list", "formula_review_list", "list_review_list",
    "step_review_list", "comparison_review_list", "note_list", "note_detail",
    "review_definition", "review_formula", "review_list", "practice_formula",
    "formula_reconstruction", "practice_definition_review", "practice_definition_match", "practice_definition_term_match", "practice_step_review",
    "practice_comparison_review", "read_review_item", "read_definition",
}
LIBRARY_ROUTES = {"review_definitions", "review_formulas", "review_lists", "review_steps", "review_comparisons", "review_notes"}
DEFINITION_EDIT_RESUME_SALT = "studigarden.definition-edit-resume.v1"
DEFINITION_EDIT_RESUME_MAX_AGE = 4 * 60 * 60


def review_origin(request):
    # GET wins, keeping the origin attached to this tab/flow, not a shared session.
    value = request.GET.get("review_origin", request.POST.get("review_origin", ""))
    return value if value in ORIGINS else ""


def with_origin(url, origin):
    """Append only a validated enum to local application routes."""
    parts = urlsplit(url)
    if origin not in ORIGINS or parts.scheme or parts.netloc or not parts.path.startswith("/") or "\\" in url:
        return url
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "review_origin"]
    query.append(("review_origin", origin))
    return urlunsplit(("", "", parts.path, urlencode(query), parts.fragment))


def subject_index(request, subject):
    """Resolve the owned subject rather than trusting a query-string index."""
    if subject is None or getattr(subject, "user_id", None) != request.user.pk:
        return None
    for index, entry in enumerate(request.session.get("onboarding_subjects", [])):
        try:
            if int(entry.get("database_id")) == subject.pk:
                return index
        except (AttributeError, TypeError, ValueError):
            continue
    from .models import Subject
    ids = list(Subject.objects.filter(user=request.user).order_by("created", "pk").values_list("pk", flat=True))
    return ids.index(subject.pk) if subject.pk in ids else None


def return_url(request, subject=None, library_route=None):
    origin = review_origin(request)
    if origin in {"standard", "garden"}:
        return reverse("dashboard") + "?" + urlencode({"view": origin, "review_return": "1"}) + "#today-plan"
    if origin == "library" and library_route in LIBRARY_ROUTES:
        if (
            library_route == "review_definitions"
            and request.GET.get("review_mode", request.POST.get("review_mode")) == "random"
        ):
            return reverse(library_route) + "?mode=random"
        return reverse(library_route)
    index = subject_index(request, subject)
    if index is not None:
        return reverse("subject_detail", kwargs={"subject_index": index}) + "?review_return=1"
    return reverse("dashboard")


def definition_edit_resume_token(
    request,
    definition,
    next_definition,
    review_scope,
    subject_index_value,
    review_mode,
):
    """Sign the next step in a completed definition-review flow.

    Editing must not accept a free-form return URL. This small signed payload
    contains only IDs and validated review settings, so a student returns to
    the next legitimate item in the same review flow after saving or cancelling.
    """
    return signing.dumps(
        {
            "user_id": request.user.pk,
            "definition_id": definition.pk,
            "subject_id": definition.knowledge_unit.subject_id,
            "next_definition_id": (
                next_definition.pk if next_definition is not None else None
            ),
            "review_scope": (
                review_scope if review_scope in {"global", "subject"} else "global"
            ),
            "subject_index": subject_index_value,
            "review_mode": "random" if review_mode == "random" else "",
            "review_origin": review_origin(request),
        },
        salt=DEFINITION_EDIT_RESUME_SALT,
        compress=True,
    )


def _definition_edit_finish_url(request, subject, origin, review_mode):
    """Return to the correct review home if there is no following item."""
    if review_mode == "random":
        query = {"review_mode": "random"}
        if origin:
            query["review_origin"] = origin
        return reverse(
            "practice_definition_match",
            kwargs={"subject_id": subject.pk},
        ) + "?" + urlencode(query)

    if origin in {"standard", "garden"}:
        return reverse("dashboard") + "?" + urlencode(
            {"view": origin, "review_return": "1"}
        ) + "#today-plan"

    if origin == "library":
        return reverse("review_definitions")

    current_subject_index = subject_index(request, subject)
    if current_subject_index is not None:
        return reverse(
            "subject_detail",
            kwargs={"subject_index": current_subject_index},
        ) + "?" + urlencode({"review_return": "1"})
    return reverse("dashboard")


def definition_edit_resume_url(request, definition, token):
    """Validate an edit-return token and resolve its next safe destination."""
    if not token:
        return None

    try:
        payload = signing.loads(
            token,
            salt=DEFINITION_EDIT_RESUME_SALT,
            max_age=DEFINITION_EDIT_RESUME_MAX_AGE,
        )
    except signing.BadSignature:
        return None

    subject = definition.knowledge_unit.subject
    if (
        payload.get("user_id") != request.user.pk
        or payload.get("definition_id") != definition.pk
        or payload.get("subject_id") != subject.pk
    ):
        return None

    review_scope = payload.get("review_scope")
    if review_scope not in {"global", "subject"}:
        return None

    review_mode = "random" if payload.get("review_mode") == "random" else ""
    origin = payload.get("review_origin")
    if origin not in ORIGINS:
        origin = ""

    # Random definition review always returns to its random-question chooser.
    if review_mode == "random":
        return _definition_edit_finish_url(request, subject, origin, review_mode)

    next_definition_id = payload.get("next_definition_id")
    try:
        next_definition_id = int(next_definition_id)
    except (TypeError, ValueError):
        next_definition_id = None

    if next_definition_id:
        from accounts.entitlements import accessible_subjects
        from .models import Definition

        next_definition = (
            Definition.objects.filter(
                pk=next_definition_id,
                knowledge_unit__subject__in=accessible_subjects(request.user),
                knowledge_unit__active=True,
            )
            .select_related("knowledge_unit", "knowledge_unit__subject")
            .first()
        )
        if next_definition is not None:
            if review_scope == "subject" and (
                next_definition.knowledge_unit.subject_id != subject.pk
            ):
                return None

            query = {"review_scope": review_scope}
            if review_scope == "subject":
                next_subject_index = subject_index(request, subject)
                if next_subject_index is not None:
                    query["subject_index"] = next_subject_index
            if origin:
                query["review_origin"] = origin
            return reverse(
                "practice_definition_review",
                kwargs={"definition_id": next_definition.pk},
            ) + "?" + urlencode(query)

    return _definition_edit_finish_url(request, subject, origin, review_mode)


def review_navigation(view):
    """Keep a flow's origin through existing server-side next/finish redirects."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        origin = review_origin(request)
        if not origin or response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.get("Location", "")
        parts = urlsplit(location)
        if parts.scheme or parts.netloc or not parts.path.startswith("/") or "\\" in location:
            return response
        try:
            match = resolve(parts.path)
        except Resolver404:
            return response
        if match.url_name in REVIEW_ROUTES:
            response["Location"] = with_origin(location, origin)
        elif match.url_name == "subject_detail" and origin in {"standard", "garden"}:
            response["Location"] = return_url(request)
        elif match.url_name == "subject_detail" and origin == "subject":
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            query["review_return"] = "1"
            response["Location"] = urlunsplit(("", "", parts.path, urlencode(query), parts.fragment))
        return response
    return wrapped

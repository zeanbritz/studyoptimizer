"""Explicit, per-flow review origins. Never accept a return URL from a client."""

from functools import wraps
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.urls import Resolver404, resolve, reverse


ORIGINS = {"standard", "garden", "subject", "library"}
REVIEW_ROUTES = {
    "definition_review_list", "formula_review_list", "list_review_list",
    "step_review_list", "comparison_review_list", "note_list", "note_detail",
    "review_definition", "review_formula", "review_list", "practice_formula",
    "formula_reconstruction", "practice_definition_review", "practice_step_review",
    "practice_comparison_review", "read_review_item", "read_definition",
}
LIBRARY_ROUTES = {"review_definitions", "review_formulas", "review_lists", "review_steps", "review_comparisons", "review_notes"}


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
        return reverse(library_route)
    index = subject_index(request, subject)
    if index is not None:
        return reverse("subject_detail", kwargs={"subject_index": index}) + "?review_return=1"
    return reverse("dashboard")


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

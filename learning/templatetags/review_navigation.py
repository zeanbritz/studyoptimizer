from django import template
from django.utils.html import format_html

from learning.review_navigation import LIBRARY_ROUTES, return_url, review_origin, with_origin

register = template.Library()


@register.simple_tag(takes_context=True)
def review_back(context):
    request = context["request"]
    subject = context.get("subject")
    if isinstance(subject, dict):
        from learning.models import Subject
        owned = Subject.objects.filter(user=request.user)
        try:
            subject = owned.filter(pk=int(subject.get("database_id"))).first()
        except (TypeError, ValueError):
            subject = owned.filter(name=subject.get("name", "")).first()
    if subject is None:
        for key in ("definition", "formula", "list", "bullet_list", "step_list", "comparison", "item"):
            item = context.get(key)
            unit = getattr(item, "knowledge_unit", None)
            if unit is not None:
                subject = unit.subject
                break
    route = getattr(request.resolver_match, "url_name", "")
    library_route = (
        "review_notes" if "note" in route else
        "review_definitions" if "definition" in route else
        "review_formulas" if "formula" in route else
        "review_comparisons" if "comparison" in route else
        "review_steps" if "step" in route else "review_lists"
    )
    if route == "read_review_item":
        library_route = {"formula": "review_formulas", "step": "review_steps", "comparison": "review_comparisons", "list": "review_lists"}.get(context.get("kind"))
    return return_url(request, subject, library_route)


@register.filter
def review_href(url, request):
    return with_origin(url, review_origin(request))


@register.simple_tag(takes_context=True)
def review_query(context, separator="&"):
    request = context["request"]
    origin = review_origin(request)
    if not origin and getattr(request.resolver_match, "url_name", "") in LIBRARY_ROUTES:
        origin = "library"
    return format_html("{}review_origin={}", separator, origin) if origin else ""


@register.simple_tag(takes_context=True)
def review_hidden(context):
    origin = review_origin(context["request"])
    return format_html('<input type="hidden" name="review_origin" value="{}">', origin) if origin else ""

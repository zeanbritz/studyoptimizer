"""Direct-route protection complements the scoped aggregate study queries."""

from django.shortcuts import render

from learning.models import BulletList, Comparison, Definition, Formula, Note, StepList, Subject

from .entitlements import accessible_subjects, get_subject_limit


ITEM_MODELS = {
    "formula_id": Formula, "definition_id": Definition, "list_id": BulletList,
    "step_list_id": StepList, "comparison_id": Comparison, "note_id": Note,
}
READ_MODELS = {"formula": Formula, "list": BulletList, "step": StepList, "comparison": Comparison}


def frozen_subject_response(request, view, kwargs):
    """Never trust a URL, posted ID or an old browser tab as an entitlement.

    Other users' records are left to the views' normal ownership/404 checks.
    This guard runs before the view, including before uploads, reviews and deletes.
    """
    if not request.user.is_authenticated or view.__module__.split(".")[0] not in {
        "dashboard", "learning", "practice", "exams",
    }:
        return None
    allowed = accessible_subjects(request.user)
    candidates = set()

    def positive_id(value):
        try:
            return int(value) if int(value) > 0 else None
        except (TypeError, ValueError):
            return None

    def remember_subject(value):
        pk = positive_id(value)
        if pk and Subject.objects.filter(pk=pk, user=request.user).exists():
            candidates.add(pk)

    for value in (kwargs.get("subject_id"), request.GET.get("subject_id"), request.POST.get("subject_id")):
        remember_subject(value)

    index = kwargs.get("subject_index")
    if index is not None:
        # The original routes use the oldest-created subject's session position.
        owned = Subject.objects.filter(user=request.user).order_by("created", "pk")
        subject_id = owned.values_list("pk", flat=True)[index:index + 1].first()
        if subject_id:
            candidates.add(subject_id)
        # A blank onboarding slot cannot bypass the plan's subject cap either.
        limit = get_subject_limit(request.user)
        if limit is not None and index >= limit:
            return render(request, "accounts/subject_frozen.html", status=403)

    model_ids = [(model, kwargs.get(key)) for key, model in ITEM_MODELS.items()]
    model_ids.extend((model, request.POST.get(key)) for key, model in ITEM_MODELS.items())
    if kwargs.get("kind") in READ_MODELS:
        model_ids.append((READ_MODELS[kwargs["kind"]], kwargs.get("item_id")))
    for model, value in model_ids:
        pk = positive_id(value)
        if not pk:
            continue
        subject_path = "subject" if model is Note else "knowledge_unit__subject"
        subject_id = model.objects.filter(
            pk=pk, **{f"{subject_path}__user": request.user},
        ).values_list(f"{subject_path}_id", flat=True).first()
        if subject_id:
            candidates.add(subject_id)

    from dashboard.models import SubjectTextbook

    for key in ("book_id", "textbook_id"):
        pk = positive_id(request.POST.get(key))
        if pk:
            subject_id = SubjectTextbook.objects.filter(
                pk=pk, subject__user=request.user,
            ).values_list("subject_id", flat=True).first()
            if subject_id:
                candidates.add(subject_id)

    if view.__module__.split(".")[0] == "exams":
        from exams.models import AssessmentEvent

        remember_subject(request.POST.get("subject"))
        for value in (request.POST.get("event_id"), request.GET.get("edit")):
            pk = positive_id(value)
            if pk:
                subject_id = AssessmentEvent.objects.filter(
                    pk=pk, subject__user=request.user,
                ).values_list("subject_id", flat=True).first()
                if subject_id:
                    candidates.add(subject_id)

    if candidates - set(allowed.filter(pk__in=candidates).values_list("pk", flat=True)):
        return render(request, "accounts/subject_frozen.html", status=403)
    return None

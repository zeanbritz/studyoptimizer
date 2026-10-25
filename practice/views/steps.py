import json
import math
import random
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from accounts.entitlements import accessible_subjects
from learning.models import StepList, StudentKnowledge


STEP_QUESTION_SALT = "studigarden.step-ordering.v1"


def get_review_interval(mastery_level):
    return {
        0: 0,
        1: 1,
        2: 2,
        3: 4,
        4: 7,
        5: 14,
        6: 30,
    }.get(mastery_level, 0)


def normalize_step_answer(value):
    """Retained for callers that imported the old text-answer helper."""
    return " ".join(str(value or "").strip().casefold().split())


def get_step_hidden_count(total_steps, mastery_level):
    """Return how many complete step blocks the learner must place.

    The function name is retained for backwards compatibility. Mastery may be
    fractional, so it must not be rounded before applying the difficulty rule.
    """
    if total_steps <= 0:
        return 0
    if total_steps <= 2:
        return total_steps

    try:
        mastery_score = float(mastery_level or 0)
    except (TypeError, ValueError):
        mastery_score = 0
    mastery_score = max(0, min(6, mastery_score))
    return min(
        total_steps,
        max(2, math.ceil(total_steps * mastery_score / 6)),
    )


def choose_required_positions(total_steps, steps_to_place, rng=None):
    """Choose missing positions across the sequence instead of just its start."""
    if total_steps <= 0 or steps_to_place <= 0:
        return []
    if steps_to_place >= total_steps:
        return list(range(total_steps))

    rng = rng or random
    positions = []
    for bucket in range(steps_to_place):
        start = math.floor(bucket * total_steps / steps_to_place)
        end = math.floor((bucket + 1) * total_steps / steps_to_place) - 1
        positions.append(rng.randint(start, max(start, end)))
    return sorted(positions)


def build_step_question(step_list, steps, progress, rng=None):
    """Create a signed, replay-resistant ordering question."""
    rng = rng or random
    steps_to_place = get_step_hidden_count(len(steps), progress.mastery_level)
    required_positions = choose_required_positions(
        len(steps),
        steps_to_place,
        rng=rng,
    )
    required_ids = [steps[position].id for position in required_positions]
    required_set = set(required_ids)
    prefilled_ids = [step.id for step in steps if step.id not in required_set]
    available_order = list(required_ids)
    rng.shuffle(available_order)

    state = {
        "step_list_id": step_list.id,
        "mastery_level": progress.mastery_level,
        "review_count": progress.review_count,
        "required_ids": required_ids,
        "prefilled_ids": prefilled_ids,
        "available_order": available_order,
    }
    return state, signing.dumps(state, salt=STEP_QUESTION_SALT, compress=True)


def load_step_question(token, step_list, steps, progress):
    """Validate the signed question against the current review and database."""
    state = signing.loads(
        token,
        salt=STEP_QUESTION_SALT,
        max_age=60 * 60 * 24,
    )
    all_ids = [step.id for step in steps]
    required_ids = state.get("required_ids")
    prefilled_ids = state.get("prefilled_ids")
    available_order = state.get("available_order")

    if state.get("step_list_id") != step_list.id:
        raise signing.BadSignature("Wrong step set")
    if state.get("review_count") != progress.review_count:
        raise signing.BadSignature("Question has already been answered")
    if not all(isinstance(values, list) for values in (
        required_ids,
        prefilled_ids,
        available_order,
    )):
        raise signing.BadSignature("Incomplete question")
    if len(set(required_ids)) != len(required_ids):
        raise signing.BadSignature("Duplicate required step")
    if len(set(prefilled_ids)) != len(prefilled_ids):
        raise signing.BadSignature("Duplicate prefilled step")
    if set(required_ids) & set(prefilled_ids):
        raise signing.BadSignature("Overlapping question state")
    if set(required_ids) | set(prefilled_ids) != set(all_ids):
        raise signing.BadSignature("Question no longer matches this step set")
    if set(available_order) != set(required_ids) or len(available_order) != len(required_ids):
        raise signing.BadSignature("Invalid available steps")

    expected_count = get_step_hidden_count(len(steps), state.get("mastery_level"))
    if len(required_ids) != expected_count:
        raise signing.BadSignature("Invalid question difficulty")
    return state


def question_display(steps, state):
    by_id = {step.id: step for step in steps}
    prefilled = set(state["prefilled_ids"])
    return {
        "ordering_slots": [
            {
                "position": position,
                "number": position + 1,
                "locked": step.id in prefilled,
                "step": step if step.id in prefilled else None,
            }
            for position, step in enumerate(steps)
        ],
        "available_steps": [by_id[step_id] for step_id in state["available_order"]],
        "steps_to_place": len(state["required_ids"]),
        "steps_already_added": len(state["prefilled_ids"]),
    }


def find_next_due_step_list(user, subject, exclude_step_list_id=None):
    today = timezone.localdate()
    from dashboard.review_planner import get_daily_review_plan, remaining_review_ids

    planned_ids = remaining_review_ids(user, get_daily_review_plan(user, today))
    candidates = (
        StepList.objects.filter(
            knowledge_unit_id__in=planned_ids,
            knowledge_unit__subject=subject,
            knowledge_unit__active=True,
        )
        .select_related("knowledge_unit", "knowledge_unit__subject")
        .order_by("knowledge_unit__created", "id")
    )
    if exclude_step_list_id is not None:
        candidates = candidates.exclude(id=exclude_step_list_id)

    for candidate in candidates:
        candidate_progress = StudentKnowledge.objects.filter(
            student=user,
            knowledge_unit=candidate.knowledge_unit,
        ).first()
        if candidate_progress is None or candidate_progress.next_review is None:
            return candidate
        if timezone.localtime(candidate_progress.next_review).date() <= today:
            return candidate
    return None


def find_next_global_step_list(user, current_step_list_id):
    step_lists = list(
        StepList.objects.filter(
            knowledge_unit__subject__in=accessible_subjects(user),
            knowledge_unit__active=True,
        )
        .select_related("knowledge_unit", "knowledge_unit__subject")
        .order_by(
            "knowledge_unit__subject__name",
            "knowledge_unit__created",
            "id",
        )
    )
    for position, candidate in enumerate(step_lists):
        if candidate.id == current_step_list_id:
            next_position = position + 1
            return step_lists[next_position] if next_position < len(step_lists) else None
    return None


def _base_context(
    step_list,
    subject,
    subject_index,
    review_scope,
    progress,
    total_steps,
):
    return {
        "step_list": step_list,
        "subject": subject,
        "subject_index": subject_index,
        "review_scope": review_scope,
        "progress": progress,
        "mastery_level": progress.mastery_level,
        "mastery_percentage": round((progress.mastery_level / 6) * 100),
        "total_steps": total_steps,
        "attempt_complete": False,
        "result": None,
        "next_step_list": None,
        "error": None,
    }


def _fresh_question_context(context, step_list, steps, progress, rng=None):
    state, token = build_step_question(step_list, steps, progress, rng=rng)
    context.update(question_display(steps, state))
    context.update({
        "question_token": token,
        # Keep the old name available for older tests and extensions.
        "hidden_count": len(state["required_ids"]),
        "review_steps": [],
    })
    return context


@login_required
def practice_step_review(request, step_list_id):
    review_scope = request.GET.get("scope") or request.POST.get("scope") or "subject"
    review_scope = "all" if review_scope == "all" else "subject"

    step_list = get_object_or_404(
        StepList.objects.select_related(
            "knowledge_unit",
            "knowledge_unit__subject",
        ),
        id=step_list_id,
        knowledge_unit__subject__in=accessible_subjects(request.user),
        knowledge_unit__active=True,
    )
    knowledge_unit = step_list.knowledge_unit
    subject = knowledge_unit.subject

    subject_index = request.GET.get("subject_index") or request.POST.get("subject_index")
    try:
        subject_index = int(subject_index)
    except (TypeError, ValueError):
        subject_index = None

    progress, _ = StudentKnowledge.objects.get_or_create(
        student=request.user,
        knowledge_unit=knowledge_unit,
    )
    progress.mastery_level = max(0, min(6, int(progress.mastery_level or 0)))
    steps = list(step_list.steps.all().order_by("order", "id"))
    total_steps = len(steps)
    context = _base_context(
        step_list,
        subject,
        subject_index,
        review_scope,
        progress,
        total_steps,
    )

    if not steps:
        context["error"] = "This step set does not contain any steps."
        context.update({
            "steps_to_place": 0,
            "steps_already_added": 0,
            "ordering_slots": [],
            "available_steps": [],
            "hidden_count": 0,
            "review_steps": [],
        })
        return render(request, "practice/step_review.html", context)

    if request.method != "POST":
        _fresh_question_context(context, step_list, steps, progress)
        return render(request, "practice/step_review.html", context)

    try:
        state = load_step_question(
            request.POST.get("question_token", ""),
            step_list,
            steps,
            progress,
        )
        submitted_ids = json.loads(request.POST.get("ordered_step_ids", "[]"))
        submitted_ids = [int(step_id) for step_id in submitted_ids]
    except (signing.BadSignature, signing.SignatureExpired, TypeError, ValueError, json.JSONDecodeError):
        context["error"] = "This review changed unexpectedly. Please try the refreshed question."
        _fresh_question_context(context, step_list, steps, progress)
        return render(request, "practice/step_review.html", context)

    correct_ids = [step.id for step in steps]
    prefilled_ids = set(state["prefilled_ids"])
    valid_submission = (
        len(submitted_ids) == total_steps
        and len(set(submitted_ids)) == total_steps
        and set(submitted_ids) == set(correct_ids)
    )
    if valid_submission:
        for position, correct_id in enumerate(correct_ids):
            if correct_id in prefilled_ids and submitted_ids[position] != correct_id:
                valid_submission = False
                break

    if not valid_submission:
        context["error"] = "Place every available step before checking your answer."
        context.update(question_display(steps, state))
        context.update({
            "question_token": request.POST.get("question_token", ""),
            "hidden_count": len(state["required_ids"]),
            "review_steps": [],
        })
        return render(request, "practice/step_review.html", context)

    required_ids = set(state["required_ids"])
    all_correct = all(
        submitted_ids[position] == correct_id
        for position, correct_id in enumerate(correct_ids)
        if correct_id in required_ids
    )
    by_id = {step.id: step for step in steps}
    result_steps = []
    for position, correct_id in enumerate(correct_ids):
        submitted_id = submitted_ids[position]
        result_steps.append({
            "number": position + 1,
            "submitted": by_id[submitted_id],
            "expected": by_id[correct_id],
            "required": correct_id in required_ids,
            "correct": submitted_id == correct_id,
        })

    now = timezone.now()
    progress.review_count += 1
    progress.last_reviewed = now
    if all_correct:
        progress.correct_count += 1
        progress.mastery_level = min(6, progress.mastery_level + 1)
        result = "correct"
    else:
        progress.incorrect_count += 1
        progress.mastery_level = max(0, progress.mastery_level - 1)
        result = "incorrect"

    interval_days = max(1, get_review_interval(progress.mastery_level))
    progress.next_review = now + timedelta(days=interval_days)
    progress.save()

    if review_scope == "all":
        next_step_list = find_next_global_step_list(request.user, step_list.id)
    else:
        next_step_list = find_next_due_step_list(
            request.user,
            subject,
            exclude_step_list_id=step_list.id,
        )

    context.update({
        "progress": progress,
        "mastery_level": progress.mastery_level,
        "mastery_percentage": round((progress.mastery_level / 6) * 100),
        "steps_to_place": len(state["required_ids"]),
        "steps_already_added": len(state["prefilled_ids"]),
        "hidden_count": len(state["required_ids"]),
        "attempt_complete": True,
        "result": result,
        "result_steps": result_steps,
        "next_step_list": next_step_list,
        "review_steps": [],
    })
    return render(request, "practice/step_review.html", context)

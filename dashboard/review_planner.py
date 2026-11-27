"""Show scheduled reviews together and pace additional practice by study time.

The daily assignment stays in place as answers are submitted. A change to
the student's timetable, exam/revision settings, or material rebuilds it.
"""

from collections import defaultdict, deque
from bisect import bisect_left
from datetime import timedelta
from hashlib import sha256
import json

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.entitlements import accessible_subjects

from learning.models import KnowledgeUnit, StudentKnowledge

from .models import (
    DailyReviewPlan,
    StudyAvailability,
    StudyProfile,
    SubjectRevisionPlan,
    SubjectTextbook,
)


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MINUTES_PER_SUMMARY_PAGE = 3  # A starting estimate, not a measured reading speed.
REVIEW_INTERVAL_DAYS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 14, 6: 30}
REVIEW_TYPES = (
    KnowledgeUnit.KnowledgeType.DEFINITION,
    KnowledgeUnit.KnowledgeType.FORMULA,
    KnowledgeUnit.KnowledgeType.BULLET_LIST,
    KnowledgeUnit.KnowledgeType.STEPS,
    KnowledgeUnit.KnowledgeType.COMPARISON,
)
DAILY_PRACTICE_TYPES = (
    KnowledgeUnit.KnowledgeType.DEFINITION,
    KnowledgeUnit.KnowledgeType.FORMULA,
)
DAILY_PRACTICE_FLOOR_PER_TYPE = 10


def _reviewable_units(user):
    """Exclude unfinished/orphan knowledge units from the time budget."""
    return KnowledgeUnit.objects.filter(
        subject__in=accessible_subjects(user), active=True, knowledge_type__in=REVIEW_TYPES
    ).filter(
        Q(knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION, definition__isnull=False)
        | Q(knowledge_type=KnowledgeUnit.KnowledgeType.FORMULA, formula__isnull=False)
        | Q(knowledge_type=KnowledgeUnit.KnowledgeType.BULLET_LIST, bullet_list__isnull=False)
        | Q(knowledge_type=KnowledgeUnit.KnowledgeType.STEPS, step_list__isnull=False)
        | Q(knowledge_type=KnowledgeUnit.KnowledgeType.COMPARISON, comparison__isnull=False)
    )


def _time_minutes(value):
    try:
        hours, minutes = map(int, value.split(":"))
        if 0 <= hours <= 24 and 0 <= minutes < 60 and (hours < 24 or minutes == 0):
            return hours * 60 + minutes
    except (AttributeError, TypeError, ValueError):
        pass
    return 0


def weekly_minutes(user):
    """Respect the saved weekday choices; use profile hours only before setup."""
    availability = StudyAvailability.objects.filter(user=user).first()
    if availability:
        return [
            _time_minutes(getattr(availability, f"{day}_time"))
            if getattr(availability, f"{day}_enabled") else 0
            for day in WEEKDAYS
        ]
    profile = StudyProfile.objects.filter(user=user).first()
    # Keep a small starter batch before the student saves a timetable.
    fallback = round(profile.study_hours * 60 / 7) if profile and profile.study_hours else 30
    return [fallback] * 7


def _learning_dates(day, exam_date, revision_days, minutes_by_weekday):
    if not exam_date or exam_date <= day:
        return []
    if (exam_date - day).days > 730:
        return []
    dates = []
    current = day
    while current < exam_date:
        if minutes_by_weekday[current.weekday()] > 0:
            dates.append(current)
        current += timedelta(days=1)
    return dates[:-revision_days] if revision_days else dates


def _settings_and_summary(user, day):
    weekly = weekly_minutes(user)
    subjects = list(accessible_subjects(user).order_by("pk"))
    revision = {
        item.subject_id: item.revision_days or 0
        for item in SubjectRevisionPlan.objects.filter(subject__in=accessible_subjects(user))
    }
    books = list(SubjectTextbook.objects.filter(subject__in=accessible_subjects(user)).order_by("pk"))
    by_subject = defaultdict(list)
    for book in books:
        by_subject[book.subject_id].append(book)

    summary_pages = 0
    for subject in subjects:
        dates = _learning_dates(
            day, subject.exam_date, max(0, revision.get(subject.pk, 0)), weekly
        )
        if day not in dates:
            continue
        total_minutes = sum(weekly[date.weekday()] for date in dates)
        if not total_minutes:
            continue
        for book in by_subject[subject.pk]:
            if book.last_summary_date == day:
                continue
            remaining = max(0, book.page_count - book.pages_summarized)
            if remaining:
                summary_pages += min(
                    remaining,
                    max(1, int(remaining * weekly[day.weekday()] / total_minutes + 0.5)),
                )

    units_stamp = list(_reviewable_units(user).order_by("pk").values_list("pk", "estimated_minutes"))
    signature_data = {
        "planner_version": 6,
        "week": weekly,
        "subjects": [(s.pk, s.exam_date.isoformat() if s.exam_date else None, revision.get(s.pk, 0)) for s in subjects],
        "books": [(b.pk, b.subject_id, b.page_count) for b in books],
        "units": units_stamp,
    }
    signature = sha256(json.dumps(signature_data, sort_keys=True).encode()).hexdigest()
    return weekly, summary_pages * MINUTES_PER_SUMMARY_PAGE, signature


def _due(progress, day):
    if progress is None:
        return True
    if completed_daily_review(progress, day):
        return False
    # A failed attempt remains part of today's target, even if another change
    # causes the persisted plan to be rebuilt later in the day.
    if progress.last_reviewed and timezone.localtime(progress.last_reviewed).date() >= day:
        return True
    if progress.review_count == 0 or progress.next_review is None:
        return True
    return timezone.localtime(progress.next_review).date() <= day


def _attempt_minutes(unit, progress):
    # Allow one retry for low mastery and a second when error history is high.
    mastery = progress.mastery_level if progress else 0
    retries = 1 if mastery < 3 or (progress and progress.incorrect_count) else 0
    if progress and progress.review_count and progress.incorrect_count / progress.review_count >= 0.25:
        retries = 2
    return max(1, unit.estimated_minutes) * (1 + retries)


def _review_candidates(user):
    units = list(_reviewable_units(user).select_related("subject").order_by("pk"))
    progress = {
        item.knowledge_unit_id: item
        for item in StudentKnowledge.objects.filter(
            student=user, knowledge_unit_id__in=[unit.pk for unit in units]
        )
    }
    return [(unit, progress.get(unit.pk)) for unit in units]


def _practice_priority(pair):
    unit, progress = pair
    last_reviewed = progress.last_reviewed if progress else None
    return (last_reviewed is not None, last_reviewed, progress.mastery_level if progress else 0, unit.pk)


def _extra_practice_candidates(candidates, excluded_ids):
    """Return additional practice in a fair rotation across review types.

    The ten-item definition/formula floor is a minimum, not a ceiling. Once
    that baseline is in the plan, unused study time is shared between every
    available review type so a larger library can receive a larger target.
    """
    groups = defaultdict(list)
    for unit, progress in candidates:
        if unit.pk not in excluded_ids:
            groups[unit.knowledge_type].append((unit, progress))

    for group in groups.values():
        group.sort(key=_practice_priority)

    queues = {
        knowledge_type: deque(group)
        for knowledge_type, group in groups.items()
        if group
    }
    order = deque(
        knowledge_type
        for knowledge_type in REVIEW_TYPES
        if knowledge_type in queues
    )
    candidates = []
    while order:
        knowledge_type = order.popleft()
        candidates.append(queues[knowledge_type].popleft())
        if queues[knowledge_type]:
            order.append(knowledge_type)
    return candidates


def _priority(unit, progress, day):
    exam_days = (
        (unit.subject.exam_date - day).days
        if unit.subject.exam_date and unit.subject.exam_date > day else 365
    )
    due_day = timezone.localtime(progress.next_review).date() if progress and progress.next_review else day
    overdue = max(0, (day - due_day).days)
    mastery = progress.mastery_level if progress else 0
    # Exams, overdue items and weaker material come first; stable pk breaks ties.
    return (exam_days, -overdue, mastery, unit.pk)


def _choose(candidates, budget, day):
    groups = defaultdict(list)
    for unit, progress in candidates:
        groups[(unit.subject_id, unit.knowledge_type)].append((unit, progress))
    for group in groups.values():
        group.sort(key=lambda pair: _priority(*pair, day))
    # Give each subject and learning type a turn to introduce new material.
    order = sorted(
        groups, key=lambda group_key: _priority(*groups[group_key][0], day)
    )
    groups = {key: deque(group) for key, group in groups.items()}
    queue = deque(order)
    selected = []
    while queue and budget > 0:
        key = queue.popleft()
        unit, progress = groups[key].popleft()
        cost = _attempt_minutes(unit, progress)
        if cost <= budget:
            selected.append(unit.pk)
            budget -= cost
        if groups[key]:
            queue.append(key)
    return selected


def get_daily_review_plan(user, day=None):
    day = day or timezone.localdate()
    weekly, summary_estimate, signature = _settings_and_summary(user, day)
    available = weekly[day.weekday()]
    summary = min(available, summary_estimate)
    existing = DailyReviewPlan.objects.filter(user=user, day=day).first()
    if existing and existing.settings_signature == signature:
        return existing

    review_items = _review_candidates(user)
    due = [(unit, progress) for unit, progress in review_items if _due(progress, day)]
    budget = max(0, available - summary)
    ids = []

    if available > 0:
        # Scheduled reviews already have a due date. Keep the entire set
        # visible together, even when its estimated time exceeds today's budget.
        scheduled = [(unit, progress) for unit, progress in due if progress and progress.next_review]
        scheduled.sort(key=lambda pair: _priority(*pair, day))
        ids = [unit.pk for unit, _ in scheduled]

        # Count completed assignments if settings or material change mid-day.
        prior_ids = set(existing.knowledge_unit_ids) if existing else set()
        ids.extend(
            unit.pk for unit, progress in review_items
            if unit.pk in prior_ids and completed_daily_review(progress, day)
        )
        selected = set(ids)
        costs = {unit.pk: _attempt_minutes(unit, progress) for unit, progress in review_items}
        spare = max(0, budget - sum(costs[unit_id] for unit_id in ids))
        new_items = [(unit, progress) for unit, progress in due if unit.pk not in selected]
        ids.extend(_choose(new_items, spare, day))
        selected = set(ids)

        unfinished = [(unit, progress) for unit, progress in review_items if not completed_daily_review(progress, day)]
        # Supplement definitions and formulas when there are fewer than ten.
        for knowledge_type in DAILY_PRACTICE_TYPES:
            planned_count = sum(
                unit.pk in selected and unit.knowledge_type == knowledge_type
                for unit, _ in review_items
            )
            slots_needed = max(
                0,
                DAILY_PRACTICE_FLOOR_PER_TYPE - planned_count,
            )
            if not slots_needed:
                continue
            practice = sorted(
                ((unit, progress) for unit, progress in unfinished
                 if unit.knowledge_type == knowledge_type and unit.pk not in selected),
                key=_practice_priority,
            )
            supplemental_ids = [unit.pk for unit, _ in practice[:slots_needed]]
            ids.extend(supplemental_ids)
            selected.update(supplemental_ids)

        spare = max(0, budget - sum(costs[unit_id] for unit_id in ids))
        if spare:
            for unit, _ in _extra_practice_candidates(unfinished, selected):
                if costs[unit.pk] <= spare:
                    ids.append(unit.pk)
                    spare -= costs[unit.pk]
                if not spare:
                    break
    with transaction.atomic():
        plan, _ = DailyReviewPlan.objects.update_or_create(
            user=user,
            day=day,
            defaults={
                "knowledge_unit_ids": ids,
                "settings_signature": signature,
                "available_minutes": available,
                "summary_minutes": summary,
                "summary_shortfall_minutes": max(0, summary_estimate - available),
                "review_minutes": budget,
                "overdue_count": len(due),
            },
        )
    return plan


def remaining_review_ids(user, plan):
    """Keep today's batch until each item has a correct answer; never refill it."""
    progress = {
        item.knowledge_unit_id: item
        for item in StudentKnowledge.objects.filter(
            student=user, knowledge_unit_id__in=plan.knowledge_unit_ids
        )
    }
    allowed_ids = set(_reviewable_units(user).values_list("pk", flat=True))
    return [
        unit_id
        for unit_id in plan.knowledge_unit_ids
        if unit_id in allowed_ids
        and not completed_daily_review(progress.get(unit_id), plan.day)
    ]


def completed_daily_review(progress, day):
    """Return whether this item has been answered correctly on ``day``."""
    return bool(
        progress
        and progress.last_correct_review
        and timezone.localtime(progress.last_correct_review).date() >= day
    )


def review_capacity_outlook(user, day=None):
    """Flag clearly impossible near-term workloads; never promise mastery."""
    day = day or timezone.localdate()
    next_exam = accessible_subjects(user).filter(exam_date__gt=day).order_by("exam_date").values_list("exam_date", flat=True).first()
    if next_exam is None:
        return None
    if (next_exam - day).days > 730:
        return None

    weekly = weekly_minutes(user)
    subjects = list(accessible_subjects(user).filter(exam_date=next_exam))
    subject_ids = [subject.pk for subject in subjects]
    units = list(_reviewable_units(user).filter(subject_id__in=subject_ids))
    progress = {
        item.knowledge_unit_id: item
        for item in StudentKnowledge.objects.filter(
            student=user, knowledge_unit_id__in=[unit.pk for unit in units]
        )
    }
    study_dates = [
        day + timedelta(days=offset)
        for offset in range((next_exam - day).days)
    ]
    available_dates = [date for date in study_dates if weekly[date.weekday()] > 0]
    estimated_review_minutes = 0
    not_mastered_by_exam = 0
    for unit in units:
        item_progress = progress.get(unit.pk)
        mastery = item_progress.mastery_level if item_progress else 0
        next_date = (
            timezone.localtime(item_progress.next_review).date()
            if item_progress and item_progress.next_review else day
        )
        next_date = max(day, next_date)
        attempts = 0
        while next_date < next_exam:
            position = bisect_left(available_dates, next_date)
            if position == len(available_dates):
                break
            reviewed_on = available_dates[position]
            attempts += 1
            mastery = min(6, mastery + 1)  # Optimistic: every answer is correct.
            next_date = reviewed_on + timedelta(days=REVIEW_INTERVAL_DAYS[mastery])
        estimated_review_minutes += attempts * _attempt_minutes(unit, item_progress)
        if mastery < 6:
            not_mastered_by_exam += 1
    total_available = sum(weekly[date.weekday()] for date in study_dates)
    # This only subtracts the next exam's remaining textbooks. Other subjects'
    # work and spacing constraints can make the real situation tighter.
    remaining_pages = sum(
        max(0, book.page_count - book.pages_summarized)
        for book in SubjectTextbook.objects.filter(subject_id__in=subject_ids)
    )
    estimated_review_capacity = max(
        0, total_available - remaining_pages * MINUTES_PER_SUMMARY_PAGE
    )
    return {
        "exam_date": next_exam,
        "subject_names": ", ".join(subject.name for subject in subjects),
        "estimated_review_minutes": estimated_review_minutes,
        "estimated_review_capacity": estimated_review_capacity,
        "shortfall_minutes": max(0, estimated_review_minutes - estimated_review_capacity),
        "shortfall_hours": (max(0, estimated_review_minutes - estimated_review_capacity) + 59) // 60,
        "not_mastered_by_exam": not_mastered_by_exam,
    }

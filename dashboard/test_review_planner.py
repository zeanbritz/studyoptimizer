from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from learning.models import Definition, KnowledgeUnit, StudentKnowledge, Subject

from .models import StudyAvailability, SubjectRevisionPlan, SubjectTextbook
from .review_planner import (
    get_daily_review_plan,
    remaining_review_ids,
    review_capacity_outlook,
)


class ReviewPlannerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="review_planner", password="Safe-test-password-123!"
        )
        self.subject = Subject.objects.create(user=self.user, name="Biology")
        self.other = Subject.objects.create(user=self.user, name="Physics")
        self.availability = StudyAvailability.objects.create(
            user=self.user,
            monday_enabled=True, monday_time="02:00",
            tuesday_enabled=True, tuesday_time="04:00",
        )

    def add_definitions(self, subject, count):
        for number in range(count):
            unit = KnowledgeUnit.objects.create(
                subject=subject,
                title=f"{subject.name} {number}",
                knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
                estimated_minutes=2,
            )
            Definition.objects.create(
                knowledge_unit=unit, term=unit.title, definition=f"Meaning {number}"
            )

    def test_longer_day_gets_twice_the_review_capacity(self):
        self.add_definitions(self.subject, 100)
        monday = timezone.localdate()
        monday += timedelta(days=(0 - monday.weekday()) % 7)
        tuesday = monday + timedelta(days=1)
        monday_plan = get_daily_review_plan(self.user, monday)
        tuesday_plan = get_daily_review_plan(self.user, tuesday)
        self.assertEqual(monday_plan.available_minutes, 120)
        self.assertEqual(tuesday_plan.available_minutes, 240)
        self.assertEqual(len(monday_plan.knowledge_unit_ids), 30)
        self.assertEqual(len(tuesday_plan.knowledge_unit_ids), 60)
        self.assertEqual(monday_plan.overdue_count, 100)

    def test_batch_does_not_refill_after_extra_practice(self):
        self.add_definitions(self.subject, 40)
        today = timezone.localdate()
        setattr(self.availability, f"{today.strftime('%A').lower()}_enabled", True)
        setattr(self.availability, f"{today.strftime('%A').lower()}_time", "00:20")
        self.availability.save()
        plan = get_daily_review_plan(self.user, today)
        original = list(plan.knowledge_unit_ids)
        self.assertTrue(original)
        StudentKnowledge.objects.create(
            student=self.user,
            knowledge_unit_id=original[0],
            review_count=1,
            last_reviewed=timezone.now(),
            next_review=timezone.now() + timedelta(days=1),
        )
        self.assertEqual(get_daily_review_plan(self.user, today).knowledge_unit_ids, original)
        self.assertNotIn(original[0], remaining_review_ids(self.user, plan))
        self.assertEqual(len(remaining_review_ids(self.user, plan)), len(original) - 1)

    def test_changed_availability_rebuilds_same_day(self):
        self.add_definitions(self.subject, 40)
        today = timezone.localdate()
        weekday = today.strftime("%A").lower()
        setattr(self.availability, f"{weekday}_enabled", True)
        setattr(self.availability, f"{weekday}_time", "00:20")
        self.availability.save()
        small = get_daily_review_plan(self.user, today)
        self.assertEqual(len(small.knowledge_unit_ids), 5)
        setattr(self.availability, f"{weekday}_time", "00:40")
        self.availability.save()
        larger = get_daily_review_plan(self.user, today)
        self.assertEqual(len(larger.knowledge_unit_ids), 10)

    def test_revision_days_release_textbook_time_for_reviews(self):
        self.add_definitions(self.subject, 100)
        monday = timezone.localdate()
        monday += timedelta(days=(0 - monday.weekday()) % 7)
        self.subject.exam_date = monday + timedelta(days=15)
        self.subject.save(update_fields=["exam_date"])
        SubjectRevisionPlan.objects.create(subject=self.subject, revision_days=2)
        SubjectTextbook.objects.create(subject=self.subject, name="Textbook", page_count=100)
        learning = get_daily_review_plan(self.user, monday)
        revision = get_daily_review_plan(self.user, monday + timedelta(days=8))
        self.assertGreater(learning.summary_minutes, 0)
        self.assertEqual(revision.summary_minutes, 0)
        self.assertGreater(len(revision.knowledge_unit_ids), len(learning.knowledge_unit_ids))

    def test_round_robin_leaves_room_for_small_subject(self):
        self.add_definitions(self.subject, 100)
        self.add_definitions(self.other, 3)
        today = timezone.localdate()
        weekday = today.strftime("%A").lower()
        setattr(self.availability, f"{weekday}_enabled", True)
        setattr(self.availability, f"{weekday}_time", "00:20")
        self.availability.save()
        plan = get_daily_review_plan(self.user, today)
        selected_other = KnowledgeUnit.objects.filter(
            pk__in=plan.knowledge_unit_ids, subject=self.other
        ).count()
        self.assertGreater(selected_other, 0)

    def test_repeated_errors_reserve_two_retries_without_granting_mastery(self):
        self.add_definitions(self.subject, 20)
        today = timezone.localdate()
        weekday = today.strftime("%A").lower()
        setattr(self.availability, f"{weekday}_enabled", True)
        setattr(self.availability, f"{weekday}_time", "00:20")
        self.availability.save()
        for unit in KnowledgeUnit.objects.filter(subject=self.subject):
            StudentKnowledge.objects.create(
                student=self.user, knowledge_unit=unit, mastery_level=1,
                review_count=4, incorrect_count=2,
                next_review=timezone.now() - timedelta(days=1),
            )
        plan = get_daily_review_plan(self.user, today)
        self.assertEqual(len(plan.knowledge_unit_ids), 3)  # 6 min each, not 2.
        self.assertEqual(
            StudentKnowledge.objects.filter(student=self.user, mastery_level=1).count(), 20
        )

    def test_outlook_warns_when_exam_work_exceeds_available_time(self):
        self.add_definitions(self.subject, 100)
        today = timezone.localdate()
        self.subject.exam_date = today + timedelta(days=7)
        self.subject.save(update_fields=["exam_date"])
        outlook = review_capacity_outlook(self.user, today)
        self.assertGreater(outlook["shortfall_minutes"], 0)
        self.assertGreater(outlook["not_mastered_by_exam"], 0)
        self.assertEqual(outlook["exam_date"], self.subject.exam_date)

    def test_explicit_day_off_has_no_assigned_reviews(self):
        self.add_definitions(self.subject, 10)
        today = timezone.localdate()
        weekday = today.strftime("%A").lower()
        setattr(self.availability, f"{weekday}_enabled", False)
        self.availability.save()
        plan = get_daily_review_plan(self.user, today)
        self.assertEqual(plan.available_minutes, 0)
        self.assertEqual(plan.knowledge_unit_ids, [])

    def test_dashboard_and_subject_list_share_the_same_batch(self):
        self.add_definitions(self.subject, 40)
        today = timezone.localdate()
        weekday = today.strftime("%A").lower()
        setattr(self.availability, f"{weekday}_enabled", True)
        setattr(self.availability, f"{weekday}_time", "00:20")
        self.availability.save()
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session["onboarding_subjects"] = [
            {"name": self.subject.name, "database_id": self.subject.pk}
        ]
        session.save()
        dashboard = self.client.get(reverse("dashboard"))
        subject_list = self.client.get(
            reverse("definition_review_list", kwargs={"subject_index": 0})
        )
        self.assertEqual(dashboard.context["due_definition_total"], 5)
        self.assertEqual(subject_list.context["due_definition_count"], 5)
        self.assertEqual(dashboard.context["review_waiting_count"], 35)

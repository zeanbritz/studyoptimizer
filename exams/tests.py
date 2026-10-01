from datetime import date, timedelta
from importlib import import_module
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from learning.models import Definition, KnowledgeUnit, Subject

from .models import AssessmentEvent
from .reminders import due_reminders


class AssessmentCalendarTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="student-a", password="safe-password")
        self.other = user_model.objects.create_user(username="student-b", password="safe-password")
        self.subject = Subject.objects.create(user=self.user, name="Biology")
        self.other_subject = Subject.objects.create(user=self.other, name="History")
        self.url = reverse("exams:calendar")

    def test_calendar_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_create_edit_and_delete_event(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
            "action": "save",
            "date": "2026-10-15",
            "subject": self.subject.pk,
            "kind": "exam",
            "title": "Paper 1",
        })
        self.assertRedirects(response, f"{self.url}?date=2026-10-15")
        event = AssessmentEvent.objects.get()
        self.assertEqual(event.subject, self.subject)

        response = self.client.get(f"{self.url}?edit={event.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paper 1")

        response = self.client.post(self.url, {
            "action": "save",
            "event_id": event.pk,
            "date": "2026-10-17",
            "subject": self.subject.pk,
            "kind": "assessment",
            "title": "Chapter 4",
        })
        self.assertRedirects(response, f"{self.url}?date=2026-10-17")
        event.refresh_from_db()
        self.assertEqual((event.date, event.kind, event.title), (
            date(2026, 10, 17), "assessment", "Chapter 4"
        ))

        response = self.client.post(self.url, {"action": "delete", "event_id": event.pk})
        self.assertRedirects(response, f"{self.url}?date=2026-10-17")
        self.assertFalse(AssessmentEvent.objects.exists())

    def test_other_students_subject_cannot_be_selected(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
            "action": "save",
            "date": "2026-10-15",
            "subject": self.other_subject.pk,
            "kind": "exam",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(AssessmentEvent.objects.exists())

    def test_other_students_event_is_hidden_and_protected(self):
        event = AssessmentEvent.objects.create(
            subject=self.other_subject,
            date=date(2026, 10, 15),
            kind="exam",
            title="Private paper",
        )
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(f"{self.url}?date=2026-10-15"), "Private paper")
        self.assertEqual(self.client.get(f"{self.url}?edit={event.pk}").status_code, 404)
        self.assertEqual(self.client.post(self.url, {
            "action": "delete", "event_id": event.pk,
        }).status_code, 404)
        self.assertEqual(self.client.post(self.url, {
            "action": "save", "event_id": event.pk,
            "date": "2026-10-16", "subject": self.subject.pk, "kind": "assessment",
        }).status_code, 404)
        event.refresh_from_db()
        self.assertEqual(event.title, "Private paper")

    def test_month_navigation_and_calendar_markers(self):
        AssessmentEvent.objects.create(
            subject=self.subject,
            date=date(2026, 12, 4),
            kind="exam",
        )
        self.client.force_login(self.user)
        response = self.client.get(f"{self.url}?month=2026-12")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "December 2026")
        self.assertContains(response, "?month=2027-01")
        self.assertContains(response, "?month=2026-11")
        self.assertContains(response, "Biology")

    def test_move_event_and_reject_other_students_event(self):
        event = AssessmentEvent.objects.create(
            subject=self.subject,
            date=date(2026, 12, 4),
            kind="assessment",
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
            "action": "move", "event_id": event.pk, "date": "2026-12-11",
        })
        self.assertRedirects(response, f"{self.url}?date=2026-12-11")
        event.refresh_from_db()
        self.assertEqual(event.date, date(2026, 12, 11))

        response = self.client.post(self.url, {
            "action": "move", "event_id": event.pk, "date": "not-a-date",
        })
        self.assertEqual(response.status_code, 400)
        event.refresh_from_db()
        self.assertEqual(event.date, date(2026, 12, 11))

        self.client.force_login(self.other)
        response = self.client.post(self.url, {
            "action": "move", "event_id": event.pk, "date": "2026-12-12",
        })
        self.assertEqual(response.status_code, 404)

    def test_next_upcoming_exam_stays_in_sync_after_calendar_changes(self):
        self.client.force_login(self.user)
        first = timezone.localdate() + timedelta(days=10)
        second = timezone.localdate() + timedelta(days=20)
        third = timezone.localdate() + timedelta(days=30)

        self.client.post(self.url, {
            "action": "save", "subject": self.subject.pk,
            "kind": "exam", "date": second.isoformat(),
        })
        self.subject.refresh_from_db()
        self.assertEqual(self.subject.exam_date, second)

        self.client.post(self.url, {
            "action": "save", "subject": self.subject.pk,
            "kind": "exam", "date": first.isoformat(),
        })
        self.subject.refresh_from_db()
        self.assertEqual(self.subject.exam_date, first)

        first_event = AssessmentEvent.objects.get(subject=self.subject, date=first)
        self.client.post(self.url, {
            "action": "move", "event_id": first_event.pk, "date": third.isoformat(),
        })
        self.subject.refresh_from_db()
        self.assertEqual(self.subject.exam_date, second)

        second_event = AssessmentEvent.objects.get(subject=self.subject, date=second)
        self.client.post(self.url, {"action": "delete", "event_id": second_event.pk})
        self.subject.refresh_from_db()
        self.assertEqual(self.subject.exam_date, third)
        self.assertEqual(
            self.client.session["onboarding_subjects"][0]["exam_date"],
            third.isoformat(),
        )

    def test_subject_detail_date_creates_edits_and_removes_calendar_exam(self):
        self.client.force_login(self.user)
        detail_url = reverse("subject_detail", args=[0])
        first = timezone.localdate() + timedelta(days=10)
        second = timezone.localdate() + timedelta(days=20)

        response = self.client.post(detail_url, {
            "action": "save_subject", "name": "Biology",
            "target_grade": "85", "exam_date": first.isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        event = AssessmentEvent.objects.get(subject=self.subject, kind="exam")
        self.assertEqual(event.date, first)

        self.client.post(detail_url, {
            "action": "save_subject", "name": "Biology",
            "target_grade": "85", "exam_date": second.isoformat(),
        })
        event.refresh_from_db()
        self.assertEqual(event.date, second)
        self.assertEqual(AssessmentEvent.objects.filter(subject=self.subject).count(), 1)

        self.client.post(detail_url, {
            "action": "save_subject", "name": "Biology",
            "target_grade": "85", "exam_date": "",
        })
        self.assertFalse(AssessmentEvent.objects.filter(subject=self.subject).exists())
        self.subject.refresh_from_db()
        self.assertIsNone(self.subject.exam_date)

    def test_existing_subject_date_is_backfilled_once(self):
        from django.apps import apps
        from django.db import connection

        backfill_subject_exams = import_module(
            "exams.migrations.0002_backfill_subject_exam_dates"
        ).backfill_subject_exams

        planned = timezone.localdate() + timedelta(days=7)
        self.subject.exam_date = planned
        self.subject.save(update_fields=["exam_date"])
        editor = type("Editor", (), {"connection": connection})()
        backfill_subject_exams(apps, editor)
        backfill_subject_exams(apps, editor)
        self.assertEqual(
            AssessmentEvent.objects.filter(
                subject=self.subject, date=planned, kind="exam"
            ).count(),
            1,
        )

    def test_past_exam_advances_to_next_upcoming_exam(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        future = timezone.localdate() + timedelta(days=7)
        AssessmentEvent.objects.create(
            subject=self.subject, date=yesterday, kind="exam"
        )
        AssessmentEvent.objects.create(
            subject=self.subject, date=future, kind="exam"
        )
        self.subject.exam_date = yesterday
        self.subject.save(update_fields=["exam_date"])

        self.client.force_login(self.user)
        self.client.get(self.url)
        self.subject.refresh_from_db()
        self.assertEqual(self.subject.exam_date, future)

    def test_changing_exam_to_assessment_clears_subject_exam_date(self):
        planned = timezone.localdate() + timedelta(days=7)
        event = AssessmentEvent.objects.create(
            subject=self.subject, date=planned, kind="exam"
        )
        self.subject.exam_date = planned
        self.subject.save(update_fields=["exam_date"])

        self.client.force_login(self.user)
        self.client.post(self.url, {
            "action": "save", "event_id": event.pk,
            "subject": self.subject.pk, "kind": "assessment",
            "date": planned.isoformat(),
        })
        self.subject.refresh_from_db()
        self.assertIsNone(self.subject.exam_date)
        event.refresh_from_db()
        self.assertEqual(event.kind, "assessment")

    def test_event_chip_is_an_edit_link_and_day_remains_a_drop_target(self):
        event = AssessmentEvent.objects.create(
            subject=self.subject, date=timezone.localdate(), kind="exam"
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertContains(response, f'href="?edit={event.pk}"')
        self.assertContains(response, f'data-event-id="{event.pk}"')
        self.assertContains(response, f'data-drop-date="{event.date.isoformat()}"')

    def test_reminder_days_saved_and_validated(self):
        self.client.force_login(self.user)
        planned = timezone.localdate() + timedelta(days=10)
        data = {
            "action": "save", "subject": self.subject.pk,
            "kind": "assessment", "date": planned.isoformat(),
            "reminder_days": "5",
        }
        self.client.post(self.url, data)
        event = AssessmentEvent.objects.get()
        self.assertEqual(event.reminder_days, 5)
        self.assertEqual(event.reminder_date, planned - timedelta(days=5))

        for invalid in ("-1", "366", "not-a-number"):
            response = self.client.post(self.url, {**data, "event_id": event.pk,
                                                   "reminder_days": invalid})
            self.assertEqual(response.status_code, 200)
            event.refresh_from_db()
            self.assertEqual(event.reminder_days, 5)

    def test_reminder_stays_visible_from_lead_day_until_completed(self):
        today = timezone.localdate()
        event = AssessmentEvent.objects.create(
            subject=self.subject, date=today + timedelta(days=4),
            kind="exam", title="Paper 1", reminder_days=3,
        )
        self.assertNotIn(event, due_reminders(self.user, today))
        for day in (today + timedelta(days=1), today + timedelta(days=2),
                    event.date, event.date + timedelta(days=1)):
            self.assertIn(event, due_reminders(self.user, day))

        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()
        with patch("django.utils.timezone.localdate", return_value=today + timedelta(days=1)):
            response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Paper 1")
        self.assertContains(response, f'data-complete-event-id="{event.pk}"')

        response = self.client.post(self.url, {
            "action": "complete", "event_id": event.pk,
            "return_to": "dashboard",
        })
        self.assertRedirects(response, reverse("dashboard"))
        event.refresh_from_db()
        self.assertIsNotNone(event.completed_at)
        self.assertNotIn(event, due_reminders(self.user, event.date))
        with patch("django.utils.timezone.localdate", return_value=today + timedelta(days=1)):
            response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "Paper 1")

    def test_dashboard_groups_event_cards_above_review(self):
        today = timezone.localdate()
        exam = AssessmentEvent.objects.create(
            subject=self.subject, date=today, kind="exam", title="Paper 1"
        )
        assessment = AssessmentEvent.objects.create(
            subject=self.subject, date=today, kind="assessment", title="Project"
        )
        unit = KnowledgeUnit.objects.create(
            subject=self.subject,
            title="Cells",
            knowledge_type=KnowledgeUnit.KnowledgeType.DEFINITION,
        )
        Definition.objects.create(
            knowledge_unit=unit, term="Cell", definition="Smallest unit of life"
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="today-plan-column plan-event plan-exam"')
        self.assertContains(response, 'class="today-plan-column plan-event plan-assessment"')
        self.assertContains(response, f'data-complete-event-id="{exam.pk}"')
        self.assertContains(response, f'data-complete-event-id="{assessment.pk}"')
        html = response.content.decode()
        self.assertLess(html.index('id="plan-events-heading"'),
                        html.index('id="plan-review-heading"'))

    def test_complete_and_reopen_exam_update_subject_date(self):
        planned = timezone.localdate() + timedelta(days=5)
        event = AssessmentEvent.objects.create(
            subject=self.subject, date=planned, kind="exam"
        )
        self.client.force_login(self.user)
        self.client.get(self.url)
        self.subject.refresh_from_db()
        self.assertEqual(self.subject.exam_date, planned)

        self.client.post(self.url, {"action": "complete", "event_id": event.pk})
        self.subject.refresh_from_db()
        self.assertIsNone(self.subject.exam_date)
        response = self.client.get(f"{self.url}?date={planned.isoformat()}")
        self.assertContains(response, "Completed")
        self.assertNotContains(response, f'data-event-id="{event.pk}"')
        self.assertNotIn(event, response.context["upcoming_events"])

        self.client.post(self.url, {"action": "reopen", "event_id": event.pk})
        event.refresh_from_db()
        self.subject.refresh_from_db()
        self.assertIsNone(event.completed_at)
        self.assertEqual(self.subject.exam_date, planned)

    def test_other_students_cannot_complete_or_reopen_events(self):
        event = AssessmentEvent.objects.create(
            subject=self.other_subject, date=timezone.localdate(), kind="exam"
        )
        self.client.force_login(self.user)
        for action in ("complete", "reopen"):
            response = self.client.post(self.url, {"action": action,
                                                   "event_id": event.pk})
            self.assertEqual(response.status_code, 404)
        event.refresh_from_db()
        self.assertIsNone(event.completed_at)

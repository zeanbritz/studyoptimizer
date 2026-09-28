from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from learning.models import Subject

from .models import AssessmentEvent


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

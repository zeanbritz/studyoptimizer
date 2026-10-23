"""Frozen subjects are retained but unavailable through all study entry points."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from dashboard.garden import garden_state
from dashboard.models import StudyProfile, SubjectTextbook
from dashboard.review_planner import remaining_review_ids
from exams.forms import AssessmentEventForm
from exams.models import AssessmentEvent
from exams.reminders import due_reminders
from learning.models import BulletList, Comparison, Definition, Formula, KnowledgeUnit, Note, StepList, StudentKnowledge, Subject

from .entitlements import accessible_subjects, can_create_learning_item, frozen_subjects
from .middleware import WorkspaceSessionPersistenceMiddleware
from .models import BetaInvite, StudyMembership, StudyMonthlyUsage


class FrozenSubjectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="frozen-student")
        cls.other = get_user_model().objects.create_user(username="other-student")
        cls.subjects = [Subject.objects.create(user=cls.user, name=f"Subject {i}") for i in range(10)]
        cls.active, cls.frozen = cls.subjects[0], cls.subjects[2]
        StudyProfile.objects.create(user=cls.user, subject_count=10, onboarding_complete=True)
        cls.items = {}
        for key, kind, model, fields in (
            ("formula", "FORMULA", Formula, {}),
            ("definition", "DEFINITION", Definition, {"term": "Private frozen term", "definition": "Private frozen content"}),
            ("list", "BULLET_LIST", BulletList, {"question": "Private frozen list"}),
            ("steps", "STEPS", StepList, {"question": "Private frozen steps"}),
            ("comparison", "COMPARISON", Comparison, {"name": "Private frozen comparison"}),
        ):
            unit = KnowledgeUnit.objects.create(subject=cls.frozen, title="Private frozen title", knowledge_type=kind)
            cls.items[key] = model.objects.create(knowledge_unit=unit, **fields)
        cls.note = Note.objects.create(subject=cls.frozen, title="Private frozen note", content="Not accessible")
        cls.allowed_unit = KnowledgeUnit.objects.create(subject=cls.active, title="Visible term", knowledge_type="DEFINITION")
        Definition.objects.create(knowledge_unit=cls.allowed_unit, term="Visible term", definition="Visible content")
        cls.event = AssessmentEvent.objects.create(subject=cls.frozen, date=timezone.localdate(), kind="exam", title="Private frozen event")
        cls.allowed_event = AssessmentEvent.objects.create(subject=cls.active, date=timezone.localdate(), kind="exam", title="Allowed event")

    def setUp(self):
        self.client.force_login(self.user)

    def paid(self, tier="grow", status="active", until=None):
        return StudyMembership.objects.update_or_create(user=self.user, defaults={
            "tier": tier, "plan": "monthly", "payment_mode": "live", "status": status,
            "paid_until": until or timezone.now() + timedelta(days=30),
        })[0]

    def ids(self):
        return set(accessible_subjects(self.user).values_list("pk", flat=True))

    def test_free_uses_creation_order_not_alphabetical_order(self):
        Subject.objects.filter(pk=self.active.pk).update(name="Zulu")
        Subject.objects.filter(pk=self.frozen.pk).update(name="Aardvark")
        self.assertEqual(self.ids(), {s.pk for s in self.subjects[:2]})
        self.assertEqual(frozen_subjects(self.user).count(), 8)
        self.assertFalse(can_create_learning_item(self.user, subject=self.frozen))

    def test_grow_seven_bloom_all_expiry_two_without_data_loss(self):
        self.paid()
        self.assertEqual(self.ids(), {s.pk for s in self.subjects[:7]})
        self.paid("bloom")
        self.assertEqual(len(self.ids()), 10)
        self.paid("bloom", "expired", timezone.now() - timedelta(seconds=1))
        self.assertEqual(len(self.ids()), 2)
        self.assertEqual(Subject.objects.filter(user=self.user).count(), 10)
        self.assertTrue(Note.objects.filter(pk=self.note.pk, content="Not accessible").exists())

    def test_cancel_keeps_paid_time_then_freezes_at_exact_boundary(self):
        end = timezone.now() + timedelta(days=3)
        self.paid("grow", "non_renewing", end)
        self.assertEqual(len(self.ids()), 7)
        with patch("accounts.access.timezone.now", return_value=end):
            self.assertEqual(len(self.ids()), 2)

    def test_beta_and_admin_unlimited_but_inactive_is_not(self):
        invite = BetaInvite.objects.first()
        invite.claimed_by = self.user
        invite.save(update_fields=["claimed_by"])
        self.assertEqual(len(self.ids()), 10)
        invite.claimed_by = None
        invite.save(update_fields=["claimed_by"])
        self.user.is_superuser = True
        self.assertEqual(len(self.ids()), 10)
        self.user.is_active = False
        self.assertEqual(len(self.ids()), 0)

    def blocked_urls(self):
        urls = [reverse("subject_detail", args=[2]), reverse("definition", args=[2])]
        for name in ("formula_review_list", "definition_review_list", "list_review_list", "step_review_list", "comparison_review_list", "book_summary"):
            urls.append(reverse(name, args=[2]))
        for name in ("create_formula", "create_definition", "create_list", "create_steps", "create_comparison", "create_note", "note_list", "formula_list", "definition_list", "download_subject_summary", "definition_pdf_lab"):
            urls.append(reverse(name, args=[self.frozen.pk]))
        for key, names in (
            ("formula", ("formula_detail", "edit_formula", "delete_formula", "review_formula", "practice_formula", "formula_reconstruction")),
            ("definition", ("edit_definition", "delete_definition", "review_definition", "practice_definition_review", "read_definition")),
            ("list", ("edit_list", "delete_list", "review_list")),
            ("steps", ("edit_steps", "delete_steps", "practice_step_review")),
            ("comparison", ("edit_comparison", "delete_comparison", "practice_comparison_review")),
        ):
            urls.extend(reverse(name, args=[self.items[key].pk]) for name in names)
        urls.extend(reverse(name, args=[self.note.pk]) for name in ("note_detail", "edit_note", "delete_note"))
        urls.extend(reverse("read_review_item", args=[kind, self.items[key].pk]) for kind, key in (
            ("formula", "formula"), ("list", "list"), ("step", "steps"), ("comparison", "comparison"),
        ))
        return urls

    def test_direct_get_and_post_cannot_read_review_edit_delete_or_export(self):
        with patch("urllib.request.build_opener", side_effect=AssertionError("No external billing allowed")):
            for url in self.blocked_urls():
                for method in (self.client.get, self.client.post):
                    with self.subTest(url=url, method=method.__name__):
                        response = method(url)
                        self.assertEqual(response.status_code, 403)
                        self.assertContains(response, "This subject is frozen", status_code=403)
                        self.assertNotContains(response, "Private frozen content", status_code=403)
        self.assertEqual(KnowledgeUnit.objects.filter(subject=self.frozen).count(), 5)
        self.assertFalse(StudentKnowledge.objects.filter(student=self.user).exists())

    def test_aggregates_exclude_frozen_content(self):
        for name in ("dashboard", "review", "review_definitions", "review_formulas", "review_lists", "review_steps", "review_comparisons", "review_notes", "progress"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "Private frozen")
        self.assertContains(self.client.get(reverse("review_definitions")), "Visible term")

    def test_calendar_forms_reminders_garden_and_event_writes(self):
        self.assertEqual(set(AssessmentEventForm(user=self.user).fields["subject"].queryset), set(self.subjects[:2]))
        self.assertEqual([e.pk for e in due_reminders(self.user, timezone.localdate())], [self.allowed_event.pk])
        state = garden_state(self.user, [], {}, [], timezone.localdate())
        self.assertEqual({tree["id"] for tree in state["trees"]}, self.ids())
        self.assertNotContains(self.client.get(reverse("exams:calendar")), "Private frozen event")
        self.assertEqual(self.client.get(reverse("exams:calendar") + f"?edit={self.event.pk}").status_code, 403)
        for action in ("delete", "complete", "reopen", "move", "save"):
            self.assertEqual(self.client.post(reverse("exams:calendar"), {
                "event_id": self.event.pk, "action": action, "date": "2027-01-01",
            }).status_code, 403)
        self.assertEqual(self.client.post(reverse("exams:calendar"), {
            "subject": self.frozen.pk, "action": "save", "date": "2027-01-01",
        }).status_code, 403)
        self.event.refresh_from_db()
        self.assertIsNone(self.event.completed_at)

    def test_session_restore_and_tampered_persistence_preserve_frozen_data(self):
        self.client.get(reverse("goals"))
        self.assertEqual([e["database_id"] for e in self.client.session["onboarding_subjects"]], [s.pk for s in self.subjects[:2]])
        self.assertEqual(StudyProfile.objects.get(user=self.user).subject_count, 10)
        request = RequestFactory().get("/")
        request.user, request.session = self.user, self.client.session
        request.session["onboarding_subjects"] = [{"database_id": self.frozen.pk, "name": "Tampered", "exam_date": "2030-01-01"}]
        WorkspaceSessionPersistenceMiddleware._save_workspace(request)
        self.frozen.refresh_from_db()
        self.assertNotEqual(self.frozen.name, "Tampered")
        self.assertNotEqual(str(self.frozen.exam_date), "2030-01-01")
        self.paid("bloom")
        self.client.get(reverse("goals"))
        self.assertEqual(len(self.client.session["onboarding_subjects"]), 10)

    def test_cached_plan_and_reset_reviews_cannot_change_frozen_progress(self):
        unit = self.items["definition"].knowledge_unit
        plan = SimpleNamespace(day=timezone.localdate(), knowledge_unit_ids=[self.allowed_unit.pk, unit.pk])
        self.assertEqual(remaining_review_ids(self.user, plan), [self.allowed_unit.pk])
        end = timezone.now() + timedelta(days=10)
        progress = StudentKnowledge.objects.create(student=self.user, knowledge_unit=unit, next_review=end)
        self.client.post(reverse("reset_today_reviews"))
        progress.refresh_from_db()
        self.assertEqual(progress.next_review, end)

    def test_profile_lists_frozen_subjects_but_not_their_material(self):
        response = self.client.get(reverse("my_plan"))
        self.assertContains(response, "Frozen subjects")
        self.assertContains(response, self.frozen.name)
        self.assertNotContains(response, "Private frozen content")
        self.assertNotContains(response, "remain available to view and review")

    def test_grow_cannot_export_or_summarize_its_eighth_subject(self):
        self.paid("grow")
        subject = self.subjects[7]
        with patch("dashboard.summary_export._collect_items", side_effect=AssertionError("Frozen export ran")):
            for name in ("download_subject_summary", "definition_pdf_lab"):
                self.assertEqual(self.client.get(reverse(name, args=[subject.pk])).status_code, 403)
        self.assertFalse(StudyMonthlyUsage.objects.filter(user=self.user).exists())

    def test_posted_ids_cannot_smuggle_frozen_items_into_an_active_subject(self):
        book = SubjectTextbook.objects.create(subject=self.frozen, name="Private book", page_count=100)
        for data in (
            {"comparison_id": self.items["comparison"].pk, "rating": "got_it"},
            {"subject_id": self.frozen.pk},
            {"textbook_id": book.pk, "action": "delete_textbook"},
            {"book_id": book.pk},
        ):
            self.assertEqual(self.client.post(reverse("subject_detail", args=[0]), data).status_code, 403)
        self.assertTrue(SubjectTextbook.objects.filter(pk=book.pk).exists())
        self.assertEqual(self.client.get(reverse("random_note_review") + f"?subject_id={self.frozen.pk}").status_code, 403)

    def test_other_owners_records_remain_hidden(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("read_definition", args=[self.items["definition"].pk])).status_code, 404)
        self.assertFalse(accessible_subjects(self.other).exists())

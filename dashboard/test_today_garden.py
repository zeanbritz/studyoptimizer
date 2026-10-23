from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from exams.models import AssessmentEvent
from exams.reminders import due_reminders
from learning.models import Definition, KnowledgeUnit, StudentKnowledge, Subject

from .garden import garden_state
from .models import StudyProfile, SubjectTextbook


class TodaysGardenTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="gardener", password="test-password")
        self.other = get_user_model().objects.create_user(username="other-gardener")
        self.math = Subject.objects.create(user=self.user, name="Mathematics")
        self.chemistry = Subject.objects.create(user=self.user, name="Chemistry")
        self.private = Subject.objects.create(user=self.other, name="Private subject")
        self.today = timezone.localdate()
        self.subjects = [{"database_id": self.math.pk}, {"database_id": self.chemistry.pk}]
        self.client.force_login(self.user)

    def state(self, groups=None, today=None):
        return garden_state(self.user, self.subjects, groups or {}, [], today or self.today)

    def test_one_leaf_per_subject_not_per_question_and_correct_destinations(self):
        groups = {"definitions": [
            {"subject": self.math, "count": 1000}, {"subject": self.chemistry, "count": 2},
            {"subject": self.private, "count": 5},
        ], "formulas": [{"subject": self.math, "count": 3}],
           "notes": [{"subject": self.chemistry, "count": 1}]}
        categories = self.state(groups)["categories"]
        self.assertEqual([c["label"] for c in categories], ["Definitions", "Formulas", "Lists", "Steps", "Comparisons", "Notes"])
        self.assertEqual(len(categories[0]["leaves"]), 2)
        self.assertEqual(categories[0]["leaves"][0]["count"], 1000)
        self.assertEqual(categories[0]["leaves"][0]["url"], reverse("definition_review_list", args=[0])+"?review_origin=garden")
        self.assertEqual(categories[1]["leaves"][0]["url"], reverse("formula_review_list", args=[0])+"?review_origin=garden")
        self.assertIn(reverse("note_list", args=[self.chemistry.pk]), categories[5]["leaves"][0]["url"])
        self.assertEqual(categories[2]["leaves"], [])
        self.assertNotIn("Private subject", str(self.state(groups)))

    def test_weighted_page_progress_and_finished_trees_are_retained(self):
        SubjectTextbook.objects.create(subject=self.math, name="Book 1", page_count=100, pages_summarized=100)
        SubjectTextbook.objects.create(subject=self.math, name="Book 2", page_count=300, pages_summarized=100)
        trees = self.state()["trees"]
        self.assertEqual(trees[0]["progress"], 50)
        self.assertEqual(trees[0]["stage"], 2)
        self.assertEqual(trees[0]["url"], reverse("book_summary", args=[0]))
        self.assertIsNone(trees[1]["progress"])
        self.assertEqual(trees[1]["stage"], 0)
        SubjectTextbook.objects.filter(subject=self.math).update(pages_summarized=300)
        tree = self.state()["trees"][0]
        self.assertEqual(tree["progress"], 100)
        self.assertEqual(tree["stage"], 5)
        self.assertEqual(tree["summarized_pages"], 400)

    def test_all_growth_thresholds(self):
        book = SubjectTextbook.objects.create(subject=self.math, name="Textbook", page_count=100)
        for pages, stage in [(0,0), (1,1), (25,1), (26,2), (50,2), (51,3), (75,3), (76,4), (99,4), (100,5)]:
            with self.subTest(pages=pages):
                book.pages_summarized=pages
                book.save()
                self.assertEqual(self.state()["trees"][0]["stage"], stage)

    def test_fruit_assignments_are_distinct_then_reused_and_never_reshuffled(self):
        from learning.garden_fruit import FRUIT_CHOICES
        # This visual-variety test needs more than the Free plan's two trees.
        # Free/Grow freezing is covered separately by FrozenSubjectTests.
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        initial = {tree["id"]: tree["fruit"] for tree in self.state()["trees"]}
        self.assertNotEqual(initial[self.math.pk], initial[self.chemistry.pk])
        for number in range(len(FRUIT_CHOICES)-2):
            Subject.objects.create(user=self.user, name=f"Extra {number}")
        varieties = [tree["fruit"] for tree in self.state()["trees"]]
        self.assertEqual(len(set(varieties)), len(FRUIT_CHOICES))
        extra = Subject.objects.create(user=self.user, name="Reused variety")
        self.assertIn(extra.garden_fruit, dict(FRUIT_CHOICES))
        self.math.name = "Renamed mathematics"
        self.math.save(update_fields=["name"])
        self.math.refresh_from_db()
        self.assertEqual(self.math.garden_fruit, initial[self.math.pk])
        extra.delete()
        refreshed = {tree["id"]: tree["fruit"] for tree in self.state()["trees"]}
        self.assertTrue(all(refreshed[pk] == fruit for pk, fruit in initial.items()))

    def test_real_events_belong_to_their_subject_with_status_and_detail_link(self):
        overdue = AssessmentEvent.objects.create(subject=self.math, date=self.today-timedelta(days=1), kind="exam", title="Algebra exam")
        complete = AssessmentEvent.objects.create(subject=self.chemistry, date=self.today+timedelta(days=3), kind="assessment", title="Lab report", completed_at=timezone.now())
        AssessmentEvent.objects.create(subject=self.private, date=self.today, kind="exam", title="Private exam")
        trees=self.state()["trees"]
        self.assertEqual([e["id"] for e in trees[0]["events"]], [overdue.pk])
        self.assertEqual(trees[0]["events"][0]["status"], "overdue")
        self.assertEqual(trees[0]["events"][0]["url"], reverse("exams:calendar")+f"?edit={overdue.pk}")
        self.assertTrue(trees[0]["events"][0]["grounded"])
        self.assertEqual(trees[1]["events"], [])
        self.assertTrue(AssessmentEvent.objects.filter(pk=complete.pk).exists())
        self.assertNotIn("Private exam", str(trees))

    def test_rescheduling_returns_fallen_fruit_and_completion_removes_it(self):
        event = AssessmentEvent.objects.create(
            subject=self.math, date=self.today-timedelta(days=2),
            kind="assessment", title="Project",
        )
        fruit = self.state()["trees"][0]["events"][0]
        self.assertTrue(fruit["grounded"])
        self.assertEqual(fruit["status"], "overdue")
        event.date = self.today + timedelta(days=10)
        event.save(update_fields=["date"])
        fruit = self.state()["trees"][0]["events"][0]
        self.assertFalse(fruit["grounded"])
        self.assertEqual(fruit["status"], "upcoming")
        self.assertEqual(fruit["url"], reverse("exams:calendar")+f"?edit={event.pk}")
        event.date = self.today-timedelta(days=2)
        event.completed_at = timezone.now()
        event.save(update_fields=["date", "completed_at"])
        self.assertEqual(self.state()["trees"][0]["events"], [])

    def test_default_exam_grows_for_a_week_before_standard_reminder_date(self):
        exam = AssessmentEvent.objects.create(
            subject=self.math, date=self.today+timedelta(days=30), kind="exam",
        )
        self.assertEqual(exam.reminder_days, 3)
        ripe_date = exam.reminder_date
        growth_start = ripe_date-timedelta(days=7)
        self.assertEqual(self.state(today=growth_start-timedelta(days=1))["trees"][0]["events"], [])
        for offset in range(8):
            with self.subTest(day=offset):
                day = growth_start+timedelta(days=offset)
                fruit = self.state(today=day)["trees"][0]["events"][0]
                self.assertAlmostEqual(fruit["fruit_ripeness"], offset/7)
                self.assertEqual(fruit["fruit_growth_start"], growth_start.isoformat())
                self.assertEqual(fruit["fruit_ripe_date"], ripe_date.isoformat())
                self.assertEqual(fruit["status"], "soon" if offset == 7 else "upcoming")
                self.assertEqual(exam in due_reminders(self.user, day), offset == 7)
        for day in (ripe_date+timedelta(days=1), exam.date, exam.date+timedelta(days=1)):
            fruit = self.state(today=day)["trees"][0]["events"][0]
            self.assertEqual(fruit["fruit_ripeness"], 1)
            self.assertEqual(fruit["grounded"], day > exam.date)
            self.assertIn(exam, due_reminders(self.user, day))

    def test_exam_milestones_match_standard_for_custom_and_zero_day_reminders(self):
        for lead in (0, 3, 7, 21, 365, 400):
            with self.subTest(reminder_days=lead):
                exam = AssessmentEvent.objects.create(
                    subject=self.math, date=self.today+timedelta(days=400),
                    kind="exam", reminder_days=lead,
                )
                ripe_date = exam.date-timedelta(days=min(lead, 365))
                for offset, expected in ((-8, None), (-7, 0), (-4, 3/7), (-1, 6/7), (0, 1)):
                    day = ripe_date+timedelta(days=offset)
                    fruit = next((item for item in self.state(today=day)["trees"][0]["events"] if item["id"] == exam.pk), None)
                    if expected is None:
                        self.assertIsNone(fruit)
                    else:
                        self.assertAlmostEqual(fruit["fruit_ripeness"], expected)
                    self.assertEqual(exam in due_reminders(self.user, day), offset == 0)
                exam.delete()

    def test_exam_rescheduling_and_reminder_edits_recalculate_fruit_on_return(self):
        exam = AssessmentEvent.objects.create(
            subject=self.math, date=self.today-timedelta(days=1), kind="exam",
        )
        self.assertTrue(self.state()["trees"][0]["events"][0]["grounded"])
        exam.date = self.today+timedelta(days=100)
        exam.save(update_fields=["date"])
        self.assertEqual(self.state()["trees"][0]["events"], [])
        exam.date = self.today+timedelta(days=10)
        exam.save(update_fields=["date"])
        fruit = self.state()["trees"][0]["events"][0]
        self.assertEqual(fruit["fruit_ripeness"], 0)
        self.assertFalse(fruit["grounded"])
        exam.reminder_days = 7
        exam.save(update_fields=["reminder_days"])
        self.assertAlmostEqual(self.state()["trees"][0]["events"][0]["fruit_ripeness"], 4/7)
        exam.completed_at = timezone.now()
        exam.save(update_fields=["completed_at"])
        self.assertEqual(self.state()["trees"][0]["events"], [])

    def test_assessment_fruit_keeps_its_existing_timing_not_exam_ripening(self):
        assessment = AssessmentEvent.objects.create(
            subject=self.math, date=self.today+timedelta(days=100),
            kind="assessment", reminder_days=2,
        )
        for days_before, status in ((100, "upcoming"), (7, "soon"), (0, "today"), (-1, "overdue")):
            day = assessment.date-timedelta(days=days_before)
            fruit = self.state(today=day)["trees"][0]["events"][0]
            self.assertEqual(fruit["id"], assessment.pk)
            self.assertEqual(fruit["status"], status)
            self.assertNotIn("fruit_ripeness", fruit)
            self.assertEqual(assessment in due_reminders(self.user, day), days_before <= 2)

    def test_multiple_exam_fruit_have_independent_ages_and_keep_subject_variety(self):
        exams = [AssessmentEvent.objects.create(
            subject=self.math, date=self.today+timedelta(days=days), kind="exam",
        ) for days in (60, 11, 10, 7, 3, 0, -1)]
        completed = AssessmentEvent.objects.create(
            subject=self.math, date=self.today+timedelta(days=2),
            kind="exam", completed_at=timezone.now(),
        )
        tree = self.state()["trees"][0]
        fruits = {fruit["id"]:fruit for fruit in tree["events"]}
        self.assertEqual(set(fruits), {event.pk for event in exams[2:]})
        self.assertNotIn(completed.pk, fruits)
        self.assertEqual(fruits[exams[2].pk]["fruit_ripeness"], 0)
        self.assertAlmostEqual(fruits[exams[3].pk]["fruit_ripeness"], 3/7)
        self.assertEqual(fruits[exams[4].pk]["fruit_ripeness"], 1)
        self.assertEqual(fruits[exams[-1].pk]["status"], "overdue")
        self.assertEqual(tree["fruit"], self.math.garden_fruit)
        self.assertEqual(self.state(today=self.today+timedelta(days=3))["trees"][0]["fruit"], tree["fruit"])

    def test_dashboard_and_live_refresh_match_growth_and_standard_attention_dates(self):
        from unittest.mock import patch
        StudyProfile.objects.create(user=self.user,onboarding_complete=True,subject_count=2)
        exam = AssessmentEvent.objects.create(
            subject=self.math, date=self.today+timedelta(days=10),
            kind="exam", title="Ripening exam", reminder_days=7,
        )
        for offset, ripeness in ((-8, None), (-7, 0), (-4, 3/7), (0, 1)):
            day = exam.reminder_date+timedelta(days=offset)
            with self.subTest(day=day), patch("django.utils.timezone.localdate", return_value=day):
                response = self.client.get(reverse("dashboard"))
                refreshed = self.client.get(reverse("dashboard")+"?garden_state=1").json()
                initial = response.context["garden_state"]
                self.assertEqual(initial, refreshed["garden"])
                fruits = initial["trees"][0]["events"]
                if ripeness is None:
                    self.assertEqual(fruits, [])
                else:
                    self.assertAlmostEqual(fruits[0]["fruit_ripeness"], ripeness)
                self.assertEqual(exam in response.context["due_assessment_events"], offset == 0)
                self.assertEqual(f'data-complete-event-id="{exam.pk}"' in refreshed["standard_html"], offset == 0)

    def test_student_can_toggle_inline_without_standalone_navigation(self):
        response=self.client.get(reverse("dashboard"))
        self.assertContains(response, 'id="plan-garden-tab"')
        self.assertContains(response, 'id="today-plan-standard"')
        self.assertContains(response, 'id="today-plan-garden"')
        self.assertNotContains(response, 'href="'+reverse("beta_garden")+'"')
        self.assertEqual(response.context["garden_state"]["student"], self.user.pk)

    def test_refresh_matches_standard_batch_and_removes_completed_leaf(self):
        unit=KnowledgeUnit.objects.create(subject=self.math,title="Atom",knowledge_type="DEFINITION",estimated_minutes=2)
        Definition.objects.create(knowledge_unit=unit,term="Atom",definition="A unit of matter")
        StudyProfile.objects.create(user=self.user,onboarding_complete=True,subject_count=2)
        url=reverse("dashboard")+"?garden_state=1"
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        state=response.json()
        self.assertEqual(state["garden"]["categories"][0]["leaves"][0]["count"],1)
        self.assertIn(reverse("definition_review_list",args=[0]),state["standard_html"])
        StudentKnowledge.objects.create(student=self.user,knowledge_unit=unit,last_reviewed=timezone.now(),next_review=timezone.now()+timedelta(days=1),review_count=1)
        state=self.client.get(url).json()
        self.assertEqual(state["garden"]["categories"][0]["leaves"],[])
        self.assertNotIn('plan-definitions',state["standard_html"])
        self.assertEqual(response["Cache-Control"],"private, no-store")

    def test_login_required_and_old_bookmarks_redirect(self):
        self.assertRedirects(self.client.get(reverse("beta_garden")), reverse("dashboard")+"?view=garden",fetch_redirect_response=False)
        self.assertEqual(self.client.post(reverse("beta_garden"),{}).status_code,405)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("dashboard")+"?garden_state=1").status_code,302)

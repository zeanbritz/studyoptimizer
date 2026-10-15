from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from learning.models import Subject

from .models import StudyProfile


class NewSubjectSetupTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="subject-setup-student",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.client.post(reverse("onboarding"), {
            "workspace_name": "Science",
            "target_grade": "80",
            "subject_count": "1",
        })

    def setup_subject(self, index=0, **changes):
        data = {
            "action": "setup_subject",
            "name": "Chemistry",
            "target_grade": "85",
            "exam_date": "2027-05-01",
            **changes,
        }
        return self.client.post(reverse("subject_detail", args=[index]), data)

    def test_unnamed_subject_opens_the_setup_popup(self):
        response = self.client.get(reverse("goals"))
        self.assertContains(response, 'data-setup-subject-index="0"')
        self.assertContains(response, 'id="subject-setup-modal"')
        self.assertContains(response, 'name="exam_date" required')

    def test_setup_saves_details_and_starts_tour(self):
        response = self.setup_subject()
        self.assertRedirects(response, reverse("subject_detail", args=[0]))
        subject = Subject.objects.get(user=self.user)
        self.assertEqual(subject.name, "Chemistry")
        self.assertEqual(subject.target_grade, 85)
        self.assertEqual(subject.exam_date.isoformat(), "2027-05-01")

        detail = self.client.get(reverse("subject_detail", args=[0]))
        self.assertContains(detail, 'id="subject-tour"')
        self.assertContains(detail, 'id="subject-tour-next"')
        self.assertContains(detail, 'id="subject-tour-done" hidden')
        self.assertEqual(self.client.session["subject_tour_pending"], 0)

        goals = self.client.get(reverse("goals"))
        self.assertNotContains(goals, 'data-setup-subject-index="0"')

    def test_add_subject_returns_to_popup_on_subjects_page(self):
        self.setup_subject()
        response = self.client.post(reverse("goals"), {"action": "add_subject"})
        self.assertRedirects(
            response,
            reverse("goals") + "?setup=1",
            fetch_redirect_response=False,
        )
        self.assertContains(self.client.get(reverse("goals")), 'data-setup-subject-index="1"')

    def test_completing_tour_is_persistent_and_idempotent_for_future_subjects(self):
        self.setup_subject()
        url = reverse("subject_detail", args=[0])
        response = self.client.post(url, {"action": "complete_subject_tour"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertTrue(StudyProfile.objects.get(user=self.user).subject_tour_completed)
        self.assertNotIn("subject_tour_pending", self.client.session)
        self.assertNotContains(self.client.get(url), 'id="subject-tour"')

        self.client.post(reverse("goals"), {"action": "add_subject"})
        self.setup_subject(index=1, name="Physics")
        self.assertNotContains(
            self.client.get(reverse("subject_detail", args=[1])),
            'id="subject-tour"',
        )

    def test_invalid_setup_does_not_create_subject(self):
        for change in (
            {"name": ""},
            {"target_grade": "120"},
            {"exam_date": ""},
            {"exam_date": "not-a-date"},
        ):
            with self.subTest(change=change):
                response = self.setup_subject(**change)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(Subject.objects.filter(user=self.user).exists())

    def test_free_subject_limit_cannot_be_bypassed_by_setup(self):
        Subject.objects.create(user=self.user, name="Biology")
        Subject.objects.create(user=self.user, name="Physics")
        profile = StudyProfile.objects.get(user=self.user)
        profile.subject_count = 3
        profile.save(update_fields=["subject_count"])
        response = self.setup_subject(index=2)
        self.assertRedirects(response, reverse("pricing"), fetch_redirect_response=False)
        self.assertFalse(Subject.objects.filter(user=self.user, name="Chemistry").exists())
        self.assertEqual(self.client.session["onboarding_subjects"][2]["name"], "")

    def test_tour_cannot_be_completed_without_a_pending_setup(self):
        response = self.client.post(
            reverse("subject_detail", args=[0]),
            {"action": "complete_subject_tour"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(StudyProfile.objects.get(user=self.user).subject_tour_completed)

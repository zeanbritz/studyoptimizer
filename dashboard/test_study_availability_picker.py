from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import StudyAvailability, StudyProfile


class StudyAvailabilityPickerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="study-availability-student",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.setup_data = {
            "workspace_name": "Biology",
            "target_grade": "80",
            "subject_count": "1",
        }

    def test_onboarding_renders_hour_and_minute_selectors(self):
        response = self.client.get(reverse("onboarding"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="hours-monday"')
        self.assertContains(response, 'id="minutes-monday"')
        self.assertContains(response, "Optional")

    def test_onboarding_availability_is_optional(self):
        response = self.client.post(reverse("onboarding"), self.setup_data)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(StudyAvailability.objects.filter(user=self.user).exists())
        self.assertIsNone(StudyProfile.objects.get(user=self.user).study_hours)

    def test_onboarding_saves_the_same_daily_schedule_as_subjects(self):
        response = self.client.post(reverse("onboarding"), {
            **self.setup_data,
            "monday_enabled": "1",
            "monday_time": "02:30",
            "wednesday_enabled": "1",
            "wednesday_time": "01:15",
        })
        self.assertEqual(response.status_code, 302)
        saved = StudyAvailability.objects.get(user=self.user)
        self.assertTrue(saved.monday_enabled)
        self.assertEqual(saved.monday_time, "02:30")
        self.assertTrue(saved.wednesday_enabled)
        self.assertEqual(saved.wednesday_time, "01:15")
        self.assertFalse(saved.tuesday_enabled)
        self.assertEqual(StudyProfile.objects.get(user=self.user).study_hours, 4)

        subjects = self.client.get(reverse("goals"))
        self.assertContains(subjects, 'id="hours-monday"')
        self.assertContains(subjects, 'value="2" selected')
        self.assertContains(subjects, 'value="30" selected')

    def test_subjects_autosave_updates_schedule_and_weekly_estimate(self):
        self.client.post(reverse("onboarding"), self.setup_data)
        response = self.client.post(
            reverse("goals"),
            {
                "action": "update_availability",
                "thursday_enabled": "1",
                "thursday_time": "00:45",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        saved = StudyAvailability.objects.get(user=self.user)
        self.assertEqual(saved.thursday_time, "00:45")
        self.assertEqual(StudyProfile.objects.get(user=self.user).study_hours, 1)

    def test_invalid_duration_does_not_save_partial_availability(self):
        self.client.post(reverse("onboarding"), self.setup_data)
        response = self.client.post(
            reverse("goals"),
            {
                "action": "update_availability",
                "monday_enabled": "1",
                "monday_time": "02:00",
                "tuesday_enabled": "1",
                "tuesday_time": "24:30",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        saved = StudyAvailability.objects.get(user=self.user)
        self.assertFalse(saved.monday_enabled)
        self.assertFalse(saved.tuesday_enabled)

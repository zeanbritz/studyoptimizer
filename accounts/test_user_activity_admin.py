from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.middleware import UserActivityMiddleware
from accounts.models import UserActivity


class UserActivityTrackingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="activity-student",
            email="activity@example.com",
        )
        self.factory = RequestFactory()

    def test_login_and_logout_are_recorded_and_login_count_increments(self):
        login_request = self.factory.post("/login/")
        user_logged_in.send(
            sender=get_user_model(),
            request=login_request,
            user=self.user,
        )
        user_logged_out.send(
            sender=get_user_model(),
            request=self.factory.post("/logout/"),
            user=self.user,
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.login_count, 1)
        self.assertEqual(
            list(
                UserActivity.objects.filter(user=self.user).values_list(
                    "label", flat=True
                )
            ),
            ["Signed out", "Signed in"],
        )

    def test_dashboard_page_view_is_recorded_without_query_parameters(self):
        request = self.factory.get("/dashboard/?private=not-recorded")
        SessionMiddleware(lambda request: HttpResponse()).process_request(request)
        request.session.save()
        request.user = self.user

        response = UserActivityMiddleware(
            lambda request: HttpResponse(status=200)
        )(request)

        self.assertEqual(response.status_code, 200)
        activity = UserActivity.objects.get(user=self.user)
        self.assertEqual(activity.activity_type, UserActivity.ActivityType.PAGE_VIEW)
        self.assertEqual(activity.label, "Viewed Today's Plan")
        self.assertEqual(activity.path, "/dashboard/")


class UserActivityAdminTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="Safe-test-password-123!",
        )
        self.student = get_user_model().objects.create_user(
            username="student",
            email="student@example.com",
        )
        UserActivity.objects.create(
            user=self.student,
            activity_type=UserActivity.ActivityType.STUDY_ACTION,
            label="Added a definition",
            path="/learning/subjects/1/definition/create/",
        )
        self.client.force_login(self.admin_user)

    def test_email_links_to_admin_user_profile_with_account_activity(self):
        changelist = self.client.get(reverse("admin:accounts_user_changelist"))
        self.assertContains(changelist, self.student.email)
        self.assertContains(
            changelist,
            reverse("admin:accounts_user_change", args=[self.student.pk]),
        )

        detail = self.client.get(
            reverse("admin:accounts_user_change", args=[self.student.pk])
        )
        self.assertContains(detail, "Account activity")
        self.assertContains(detail, "Last login")
        self.assertContains(detail, "Login count")
        self.assertContains(detail, "Recent website activity")
        self.assertContains(detail, "Added a definition")

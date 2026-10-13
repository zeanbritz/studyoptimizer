from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse


class LandingHomeTests(TestCase):
    def test_home_explains_study_flow_and_offers_public_signup(self):
        response = self.client.get(reverse("landing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Less planning.")
        self.assertContains(response, "A study day you can actually try.")
        self.assertContains(response, 'href="#experience"')
        self.assertContains(response, 'role="tablist"')
        self.assertContains(response, 'id="demo-panel-review"')
        self.assertContains(response, 'id="demo-panel-subjects"')
        self.assertContains(response, 'id="demo-panel-progress"')
        self.assertContains(response, 'id="demo-panel-profile"')
        self.assertContains(response, 'data-demo-open="formula"')
        self.assertContains(response, 'data-demo-open="definition"')
        self.assertContains(response, 'data-answer="pi"')
        self.assertContains(response, 'data-answer="smallest"')
        self.assertContains(response, "Nothing here is saved to an account.")
        self.assertContains(response, 'href="#why"')
        self.assertContains(response, reverse("pricing"))
        self.assertContains(response, 'href="' + reverse("register") + '"')
        self.assertContains(response, ">Sign up</a>")
        self.assertNotContains(response, "Try the sample dashboard")
        self.assertNotContains(response, "Start for free")
        self.assertNotContains(response, 'class="demo-tab__arrow"')
        self.assertNotContains(response, "↗")

    def test_pricing_shows_free_signup_without_invite_language(self):
        response = self.client.get(reverse("pricing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign up for free")
        self.assertContains(response, 'href="' + reverse("register") + '"')
        self.assertNotContains(response, "Use an invite")
        self.assertNotContains(response, "Invite-only beta")

    def test_signed_in_student_has_dashboard_route(self):
        user = get_user_model().objects.create_user(
            username="landing_student", password="sample-password"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("landing"))

        self.assertContains(response, 'href="' + reverse("dashboard") + '"')
        self.assertContains(response, 'action="' + reverse("logout") + '"')
        self.assertNotContains(response, "Sign in")

    def test_home_assets_exist(self):
        for asset in (
            "landing/css/home.css",
            "landing/css/home-demo.css",
            "landing/css/home-sections.css",
            "landing/css/home-responsive.css",
            "landing/css/home-app.css",
            "landing/js/home.js",
            "landing/images/study-pages-v1.webp",
            "images/logo.webp",
        ):
            with self.subTest(asset=asset):
                self.assertIsNotNone(finders.find(asset))

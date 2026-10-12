from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse


class LandingHomeTests(TestCase):
    def test_home_explains_study_flow_without_premature_signup_claim(self):
        response = self.client.get(reverse("landing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stop planning your studying.")
        self.assertContains(response, "Actual StudiGarden screens")
        self.assertContains(response, 'href="#experience"')
        self.assertContains(response, 'role="tablist"')
        self.assertContains(response, 'id="demo-panel-review"')
        self.assertContains(response, 'id="demo-panel-subjects"')
        self.assertContains(response, 'href="#why"')
        self.assertContains(response, reverse("pricing"))
        self.assertNotContains(response, 'href="' + reverse("register") + '"')
        self.assertNotContains(response, "Start for free")
        self.assertNotContains(response, 'class="demo-tab__arrow"')
        self.assertNotContains(response, "↗")

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
            "landing/js/home.js",
            "landing/images/study-desk-hero-v1.webp",
            "landing/images/study-pages-v1.webp",
            "landing/images/product-todays-plan.jpg",
            "landing/images/product-subjects.jpg",
            "landing/images/product-review.jpg",
            "landing/images/product-exams.jpg",
        ):
            with self.subTest(asset=asset):
                self.assertIsNotNone(finders.find(asset))

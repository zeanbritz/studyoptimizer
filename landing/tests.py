from html.parser import HTMLParser

from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase
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

    def test_pricing_shows_free_grow_and_bloom_with_checkout_closed(self):
        response = self.client.get(reverse("pricing"))
        self.assertContains(response, '>Free</h2>')
        self.assertContains(response, '>Grow</h2>')
        self.assertContains(response, '>Bloom</h2>')
        for price in ("R0", "R35", "R90"):
            self.assertContains(response, price)
        self.assertContains(response, "Create up to 2 subjects")
        self.assertContains(response, "Create up to 100 learning items")
        self.assertContains(response, "Grow coming soon")
        self.assertContains(response, "Bloom coming soon")
        self.assertContains(response, "class=\"button button-unavailable\" disabled", count=2)
        self.assertNotContains(response, "R99")
        self.assertNotContains(response, "Yearly")

    def test_billing_page_uses_the_new_monthly_prices(self):
        response = self.client.get(reverse("billing_policy"))
        self.assertContains(response, "Free at R0")
        self.assertContains(response, "Grow at R35 per month")
        self.assertContains(response, "Bloom at R90 per month")
        self.assertNotContains(response, "R99")

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


class SidebarLogoTests(SimpleTestCase):
    def test_desktop_and_mobile_brand_links_open_the_landing_page(self):
        class LinkParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self.links.append(dict(attrs))

        request = RequestFactory().get("/dashboard/")
        request.user = AnonymousUser()
        markup = render_to_string(
            "partials/sidebar.html",
            {"user": request.user, "active_page": "dashboard"},
            request=request,
        )
        parser = LinkParser()
        parser.feed(markup)
        brand_links = [
            link for link in parser.links
            if {"logo", "mobile-topbar-brand"}.intersection(link.get("class", "").split())
        ]
        self.assertEqual(len(brand_links), 2)
        for link in brand_links:
            self.assertEqual(link["href"], reverse("landing"))
            self.assertEqual(link["aria-label"], "StudiGarden home")
        self.assertTrue(any(
            link.get("href") == reverse("dashboard")
            and "nav-link" in link.get("class", "").split()
            for link in parser.links
        ))

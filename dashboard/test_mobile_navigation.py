from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import SimpleTestCase


class MobileNavigationTests(SimpleTestCase):
    def test_shared_sidebar_has_mobile_menu_controls(self):
        html = render_to_string(
            "partials/sidebar.html",
            {"user": AnonymousUser()},
        )

        self.assertIn('class="mobile-topbar"', html)
        self.assertIn('aria-controls="sidebar"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('class="mobile-sidebar-backdrop"', html)
        self.assertIn('class="mobile-sidebar-close"', html)
        self.assertIn('id="sidebar"', html)
        self.assertIn('dashboard/js/sidebar.', html)

import importlib
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import TestCase

from .access import has_permanent_free_access
from .models import BetaInvite


class PermanentFreeAccessTests(TestCase):
    def test_anonymous_and_regular_users_are_not_grandfathered(self):
        student = get_user_model().objects.create_user(
            username="regular",
            password="Safe-test-password-123!",
        )

        self.assertFalse(has_permanent_free_access(None))
        self.assertFalse(has_permanent_free_access(AnonymousUser()))
        self.assertFalse(has_permanent_free_access(student))

    def test_beta_flag_grants_permanent_free_access(self):
        student = get_user_model().objects.create_user(
            username="beta",
            password="Safe-test-password-123!",
            beta_lifetime_access=True,
        )

        self.assertTrue(has_permanent_free_access(student))

        student.refresh_from_db()
        self.assertTrue(has_permanent_free_access(student))

        student.is_active = False
        self.assertFalse(has_permanent_free_access(student))

    def test_claimed_invite_is_a_fallback_even_when_paused(self):
        student = get_user_model().objects.create_user(
            username="claimed",
            password="Safe-test-password-123!",
        )
        invite = BetaInvite.objects.get(slot=1)
        invite.claimed_by = student
        invite.is_active = False
        invite.save(update_fields=["claimed_by", "is_active"])

        self.assertTrue(has_permanent_free_access(student))

    def test_superuser_has_free_access(self):
        owner = get_user_model().objects.create_superuser(
            username="owner",
            email="owner@example.com",
            password="Safe-test-password-123!",
        )

        self.assertTrue(has_permanent_free_access(owner))

    def test_migration_grandfathers_existing_claimed_invites(self):
        student = get_user_model().objects.create_user(
            username="existing_beta",
            password="Safe-test-password-123!",
        )
        other_student = get_user_model().objects.create_user(
            username="not_invited",
            password="Safe-test-password-123!",
        )
        invite = BetaInvite.objects.get(slot=2)
        invite.claimed_by = student
        invite.save(update_fields=["claimed_by"])

        migration = importlib.import_module(
            "accounts.migrations.0007_user_beta_lifetime_access"
        )
        migration.grandfather_claimed_beta_accounts(
            apps,
            SimpleNamespace(connection=connection),
        )

        student.refresh_from_db()
        other_student.refresh_from_db()
        self.assertTrue(student.beta_lifetime_access)
        self.assertFalse(other_student.beta_lifetime_access)

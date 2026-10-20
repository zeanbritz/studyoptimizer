from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .access import ACCESS_FREE, ACCESS_FULL, get_study_access_level, get_study_tier
from .entitlements import can_create_learning_item, can_create_subject
from .models import BetaInvite, StudyMembership, StudyPayment, StudyTier


class StudyTierAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="tier-student")

    def test_free_and_unauthenticated_accounts_are_distinct(self):
        self.assertIsNone(get_study_tier(None))
        self.assertIsNone(get_study_tier(AnonymousUser()))
        self.assertEqual(get_study_tier(self.user), StudyTier.FREE)

    def test_verified_paid_period_resolves_tier_and_subject_limit(self):
        now = timezone.now()
        for tier in (StudyTier.GROW, StudyTier.BLOOM):
            for status in (
                StudyMembership.Status.ACTIVE,
                StudyMembership.Status.NON_RENEWING,
                StudyMembership.Status.PAST_DUE,
            ):
                with self.subTest(tier=tier, status=status):
                    StudyMembership.objects.update_or_create(user=self.user, defaults={
                        "tier": tier, "plan": StudyMembership.Plan.MONTHLY,
                        "status": status, "paid_until": now + timedelta(days=5),
                    })
                    self.assertEqual(get_study_tier(self.user), tier)
                    self.assertEqual(get_study_access_level(self.user), ACCESS_FULL)
                    if tier == StudyTier.GROW:
                        self.assertTrue(can_create_subject(self.user, session_subject_count=6))
                        self.assertFalse(can_create_subject(self.user, session_subject_count=7))
                    else:
                        self.assertTrue(can_create_subject(self.user, session_subject_count=100))
                    self.assertTrue(can_create_learning_item(self.user))

    def test_pending_expired_and_unpaid_memberships_do_not_resolve_to_paid_tiers(self):
        now = timezone.now()
        for status, paid_until in (
            (StudyMembership.Status.PENDING, now + timedelta(days=5)),
            (StudyMembership.Status.EXPIRED, now + timedelta(days=5)),
            (StudyMembership.Status.ACTIVE, None),
            (StudyMembership.Status.ACTIVE, now),
        ):
            with self.subTest(status=status, paid_until=paid_until):
                StudyMembership.objects.update_or_create(user=self.user, defaults={
                    "tier": StudyTier.BLOOM, "plan": StudyMembership.Plan.MONTHLY,
                    "status": status, "paid_until": paid_until,
                })
                with patch("accounts.access.timezone.now", return_value=now):
                    self.assertEqual(get_study_tier(self.user), StudyTier.FREE)
                    self.assertEqual(get_study_access_level(self.user), ACCESS_FREE)

    def test_grace_period_keeps_the_purchased_tier_only_until_it_ends(self):
        now = timezone.now()
        member = StudyMembership.objects.create(
            user=self.user, tier=StudyTier.GROW, plan=StudyMembership.Plan.MONTHLY,
            status=StudyMembership.Status.PAST_DUE,
            paid_until=now - timedelta(days=1), grace_until=now + timedelta(days=1),
        )
        self.assertEqual(get_study_tier(self.user), StudyTier.GROW)
        member.grace_until = now
        member.save(update_fields=["grace_until"])
        with patch("accounts.access.timezone.now", return_value=now):
            self.assertEqual(get_study_tier(self.user), StudyTier.FREE)

    def test_beta_flag_claimed_invite_and_administrator_resolve_to_bloom(self):
        self.user.beta_lifetime_access = True
        self.user.save(update_fields=["beta_lifetime_access"])
        self.assertEqual(get_study_tier(self.user), StudyTier.BLOOM)

        self.user.beta_lifetime_access = False
        self.user.save(update_fields=["beta_lifetime_access"])
        invite = BetaInvite.objects.get(slot=1)
        invite.claimed_by = self.user
        invite.save(update_fields=["claimed_by"])
        self.assertEqual(get_study_tier(self.user), StudyTier.BLOOM)

        invite.claimed_by = None
        invite.save(update_fields=["claimed_by"])
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.assertEqual(get_study_tier(self.user), StudyTier.BLOOM)

        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertIsNone(get_study_tier(self.user))

    def test_only_paid_tiers_can_be_saved_on_billing_records(self):
        for tier in (StudyTier.FREE, "unknown"):
            with self.subTest(model="membership", tier=tier):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    StudyMembership.objects.create(
                        user=self.user, tier=tier, plan=StudyMembership.Plan.MONTHLY,
                    )
            with self.subTest(model="payment", tier=tier):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    StudyPayment.objects.create(
                        user=self.user, tier=tier, plan=StudyMembership.Plan.MONTHLY,
                        mode=StudyPayment.Mode.TEST, expected_amount_cents=3500,
                    )


class StudyTierMigrationTests(TransactionTestCase):
    def test_legacy_records_keep_prices_dates_and_beta_entitlement(self):
        previous = [("accounts", "0009_studypayment")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate(previous)
        old_apps = executor.loader.project_state(previous).apps
        old_user = old_apps.get_model("accounts", "User")
        old_member = old_apps.get_model("accounts", "StudyMembership")
        old_payment = old_apps.get_model("accounts", "StudyPayment")
        beta = old_user.objects.create(username="legacy-beta", beta_lifetime_access=True)
        paid_until = timezone.now() + timedelta(days=30)
        for index, (period, amount) in enumerate((("monthly", 9900), ("yearly", 99900))):
            user = old_user.objects.create(username=f"legacy-paid-{index}")
            old_member.objects.create(
                user_id=user.pk, plan=period, status="active", paid_until=paid_until,
            )
            old_payment.objects.create(
                user_id=user.pk, reference=f"SG-legacy-{index}", plan=period,
                mode="live", status="succeeded", expected_amount_cents=amount,
            )

        MigrationExecutor(connection).migrate(latest)
        for member in StudyMembership.objects.all():
            self.assertEqual(member.tier, StudyTier.BLOOM)
            self.assertEqual(member.status, StudyMembership.Status.ACTIVE)
            self.assertEqual(member.paid_until, paid_until)
        self.assertEqual(
            list(StudyPayment.objects.order_by("plan").values_list("plan", "expected_amount_cents")),
            [("monthly", 9900), ("yearly", 99900)],
        )
        self.assertFalse(StudyPayment.objects.exclude(tier=StudyTier.BLOOM).exists())
        self.assertFalse(StudyPayment.objects.exclude(paystack_plan_code="").exists())
        beta = get_user_model().objects.get(pk=beta.pk)
        self.assertTrue(beta.beta_lifetime_access)
        self.assertEqual(get_study_tier(beta), StudyTier.BLOOM)

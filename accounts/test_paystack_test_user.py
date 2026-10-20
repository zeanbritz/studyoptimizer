import io
from types import SimpleNamespace
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from .access import get_study_tier
from .management.commands.create_paystack_test_user import PREVIEW_DATABASE, _require_disposable_preview
from .models import BetaInvite, StudyMembership, StudyPayment, StudyTier


COMMAND_MODULE = "accounts.management.commands.create_paystack_test_user"
SANDBOX_SETTINGS = {
    "DEBUG": True,
    "PAYSTACK_TEST_CHECKOUT_ENABLED": True,
    "PAYSTACK_TEST_SECRET_KEY": "sk_test_dummyUserCreationKey",
}


@override_settings(**SANDBOX_SETTINGS)
class PreviewUserSafetyTests(SimpleTestCase):
    def check_database(self, **overrides):
        database = {"ENGINE": "django.db.backends.sqlite3", "NAME": PREVIEW_DATABASE}
        database.update(overrides)
        with patch(COMMAND_MODULE + ".connections", {
            "default": SimpleNamespace(settings_dict=database),
        }):
            _require_disposable_preview()

    def test_only_exact_disposable_sqlite_database_is_allowed(self):
        self.check_database()
        for name in ("db.sqlite3", "/app/db.sqlite3", "/tmp/another.sqlite3", ":memory:"):
            with self.subTest(name=name), self.assertRaises(CommandError):
                self.check_database(NAME=name)

    def test_hosted_backend_is_rejected_even_with_the_preview_name(self):
        with self.assertRaises(CommandError):
            self.check_database(ENGINE="django.db.backends.postgresql")

    def test_debug_test_flag_and_test_key_are_all_required(self):
        for setting in (
            {"DEBUG": False}, {"PAYSTACK_TEST_CHECKOUT_ENABLED": False},
            {"PAYSTACK_TEST_SECRET_KEY": "sk_live_dummy"},
            {"PAYSTACK_TEST_SECRET_KEY": ""},
        ):
            with self.subTest(setting=setting), self.settings(**setting):
                with self.assertRaises(CommandError):
                    self.check_database()

    def test_rejected_command_does_not_create_users_or_print_credentials(self):
        output = io.StringIO()
        with self.settings(DEBUG=False), patch(COMMAND_MODULE + ".get_user_model") as users:
            with self.assertRaises(CommandError):
                call_command("create_paystack_test_user", stdout=output)
        users.assert_not_called()
        self.assertEqual(output.getvalue(), "")


@override_settings(**SANDBOX_SETTINGS)
class PreviewUserCreationTests(TestCase):
    def create_tester(self, output=None):
        output = output if output is not None else io.StringIO()
        # Tests use Django's isolated test DB, never the actual preview DB.
        # The unpatched guard is covered separately above.
        with patch(COMMAND_MODULE + "._require_disposable_preview"):
            call_command("create_paystack_test_user", stdout=output)
        return output.getvalue()

    def test_creates_verified_free_user_with_working_random_password_and_no_network(self):
        with patch("accounts.paystack_client.build_opener") as network:
            output = self.create_tester()
        network.assert_not_called()
        username = next(line.removeprefix("Username: ") for line in output.splitlines() if line.startswith("Username: "))
        password = next(line.removeprefix("Password: ") for line in output.splitlines() if line.startswith("Password: "))
        user = get_user_model().objects.get(username=username)
        self.assertTrue(user.check_password(password))
        self.assertGreaterEqual(len(password), 24)
        self.assertEqual(user.email, username + "@example.com")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.beta_lifetime_access)
        self.assertEqual(get_study_tier(user), StudyTier.FREE)
        self.assertTrue(EmailAddress.objects.filter(
            user=user, email=user.email, primary=True, verified=True,
        ).exists())
        self.assertFalse(StudyMembership.objects.filter(user=user).exists())
        self.assertFalse(StudyPayment.objects.filter(user=user).exists())
        self.assertFalse(BetaInvite.objects.filter(claimed_by=user).exists())
        self.assertNotIn("sk_test_dummyUserCreationKey", output)

    def test_repeated_use_creates_different_users_not_overwrites(self):
        self.create_tester()
        self.create_tester()
        users = get_user_model().objects.filter(username__startswith="growtest-")
        self.assertEqual(users.count(), 2)
        self.assertEqual(EmailAddress.objects.filter(user__in=users, verified=True).count(), 2)

    def test_existing_users_membership_history_and_beta_invites_are_untouched(self):
        user = get_user_model().objects.create_user(username="cancelled-tester", email="old@example.com")
        membership = StudyMembership.objects.create(
            user=user, tier=StudyTier.BLOOM, plan=StudyMembership.Plan.MONTHLY,
            status=StudyMembership.Status.NON_RENEWING,
            payment_mode=StudyMembership.PaymentMode.TEST,
            paystack_subscription_code="SUB_existing",
        )
        payment = StudyPayment.objects.create(
            user=user, tier=StudyTier.BLOOM, plan=StudyMembership.Plan.MONTHLY,
            mode=StudyPayment.Mode.TEST, expected_amount_cents=9000,
            status=StudyPayment.Status.SUCCEEDED,
        )
        before = list(get_user_model().objects.filter(pk=user.pk).values())
        memberships = list(StudyMembership.objects.filter(pk=membership.pk).values())
        payments = list(StudyPayment.objects.filter(pk=payment.pk).values())
        invites = list(BetaInvite.objects.values())
        self.create_tester()
        self.assertEqual(list(get_user_model().objects.filter(pk=user.pk).values()), before)
        self.assertEqual(list(StudyMembership.objects.values()), memberships)
        self.assertEqual(list(StudyPayment.objects.values()), payments)
        self.assertEqual(list(BetaInvite.objects.values()), invites)

    def test_failed_email_creation_rolls_back_user_and_prints_no_credentials(self):
        before = get_user_model().objects.count()
        output = io.StringIO()
        with patch(COMMAND_MODULE + ".EmailAddress.objects.using") as addresses:
            addresses.return_value.filter.return_value.exists.return_value = False
            addresses.return_value.create.side_effect = RuntimeError("test failure")
            with self.assertRaises(RuntimeError):
                self.create_tester(output)
        self.assertEqual(get_user_model().objects.count(), before)
        self.assertEqual(output.getvalue(), "")

    def test_username_collision_uses_another_random_name(self):
        old_user = get_user_model().objects.create_user(username="growtest-11111111")
        with patch(COMMAND_MODULE + ".secrets.token_hex", side_effect=["11111111", "22222222"]):
            self.create_tester()
        self.assertTrue(get_user_model().objects.filter(pk=old_user.pk).exists())
        self.assertTrue(get_user_model().objects.filter(username="growtest-22222222").exists())

    def test_exhausted_names_fail_without_printing_password(self):
        get_user_model().objects.create_user(username="growtest-11111111")
        before = get_user_model().objects.count()
        output = io.StringIO()
        with patch(COMMAND_MODULE + ".secrets.token_hex", return_value="11111111"):
            with self.assertRaises(CommandError):
                self.create_tester(output)
        self.assertEqual(get_user_model().objects.count(), before)
        self.assertEqual(output.getvalue(), "")

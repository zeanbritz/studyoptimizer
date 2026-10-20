"""Create an isolated checkout tester, never reset an existing paid account."""

import secrets

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from accounts.paystack_client import test_checkout_enabled


PREVIEW_DATABASE = "/tmp/studigarden-paystack-preview.sqlite3"


def _require_disposable_preview():
    if not test_checkout_enabled():
        raise CommandError(
            "Stopped: this command requires the local DEBUG sandbox and a test key."
        )
    database = connections["default"].settings_dict
    if (
        database.get("ENGINE") != "django.db.backends.sqlite3"
        or str(database.get("NAME")) != PREVIEW_DATABASE
    ):
        raise CommandError(
            "Stopped: use only the disposable Paystack preview database, "
            "not your saved local or hosted database."
        )


class Command(BaseCommand):
    help = "Create a verified Free test user only in the disposable Paystack preview."
    requires_system_checks = []

    def handle(self, *args, **options):
        _require_disposable_preview()
        users = get_user_model().objects.db_manager("default")
        password = secrets.token_urlsafe(18)

        with transaction.atomic(using="default"):
            for _ in range(10):
                username = "growtest-" + secrets.token_hex(4)
                email = username + "@example.com"
                if not (
                    users.filter(username=username).exists()
                    or users.filter(email__iexact=email).exists()
                    or EmailAddress.objects.using("default").filter(email__iexact=email).exists()
                ):
                    break
            else:
                raise CommandError("Could not choose a unique test username. Please retry.")

            user = users.create_user(
                username=username, email=email, password=password,
                is_active=True, is_staff=False, is_superuser=False,
                beta_lifetime_access=False,
            )
            EmailAddress.objects.using("default").create(
                user=user, email=user.email, primary=True, verified=True,
            )

        self.stdout.write("Created a verified Free account in your disposable local preview.")
        self.stdout.write("Existing accounts, payments and subscriptions were not changed.")
        self.stdout.write("Sign out of the current local account, then sign in at http://localhost:8000/login/")
        self.stdout.write(f"Username: {username}")
        self.stdout.write(f"Password: {password}")
        self.stdout.write("Keep this temporary password private. Use only Paystack test payment options.")

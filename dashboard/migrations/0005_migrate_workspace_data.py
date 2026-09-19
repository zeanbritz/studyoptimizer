import json
from datetime import date, datetime

from django.db import migrations


def parse_integer(value, minimum, maximum):
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        return None

    if minimum <= parsed_value <= maximum:
        return parsed_value

    return None


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if not value:
        return None

    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def migrate_workspace_data(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    StudyProfile = apps.get_model("dashboard", "StudyProfile")
    Subject = apps.get_model("learning", "Subject")

    for user in User.objects.all().iterator():
        try:
            workspace = json.loads(user.workspace_data or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            workspace = {}

        if not isinstance(workspace, dict):
            continue

        profile_data = workspace.get("onboarding_profile")
        subject_entries = workspace.get("onboarding_subjects")

        if not isinstance(profile_data, dict):
            profile_data = {}

        if not isinstance(subject_entries, list):
            subject_entries = []

        valid_subject_entries = [
            entry
            for entry in subject_entries
            if isinstance(entry, dict) and str(entry.get("name", "")).strip()
        ]

        has_workspace = bool(
            profile_data
            or valid_subject_entries
            or workspace.get("onboarding_complete")
        )

        if has_workspace:
            workspace_name = str(
                profile_data.get("workspace_name", "")
            ).strip()[:150]

            StudyProfile.objects.update_or_create(
                user_id=user.pk,
                defaults={
                    "workspace_name": workspace_name,
                    "target_grade": parse_integer(
                        profile_data.get("target_grade"),
                        0,
                        100,
                    ),
                    "study_hours": parse_integer(
                        profile_data.get("study_hours"),
                        1,
                        168,
                    ),
                    "onboarding_complete": bool(
                        workspace.get("onboarding_complete")
                        or valid_subject_entries
                    ),
                },
            )

        for entry in valid_subject_entries:
            subject = None
            database_id = entry.get("database_id")
            subject_name = str(entry.get("name", "")).strip()[:100]

            try:
                database_id = int(database_id)
            except (TypeError, ValueError):
                database_id = None

            if database_id is not None:
                subject = Subject.objects.filter(
                    pk=database_id,
                    user_id=user.pk,
                ).first()

            if subject is None:
                subject = Subject.objects.filter(
                    user_id=user.pk,
                    name=subject_name,
                ).order_by("created", "id").first()

            if subject is None:
                subject = Subject.objects.create(
                    user_id=user.pk,
                    name=subject_name,
                )

            fields_to_update = []
            target_grade = parse_integer(
                entry.get("target_grade"),
                0,
                100,
            )
            exam_date = parse_date(entry.get("exam_date"))

            if target_grade is not None:
                subject.target_grade = target_grade
                fields_to_update.append("target_grade")

            if exam_date is not None:
                subject.exam_date = exam_date
                fields_to_update.append("exam_date")

            if fields_to_update:
                subject.save(update_fields=fields_to_update)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_user_workspace_data"),
        ("dashboard", "0004_studyprofile"),
        ("learning", "0014_subject_exam_date_subject_target_grade"),
    ]

    operations = [
        migrations.RunPython(
            migrate_workspace_data,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

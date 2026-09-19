import json

import django.core.validators
from django.db import migrations, models


def populate_subject_count(apps, schema_editor):
    StudyProfile = apps.get_model("dashboard", "StudyProfile")
    Subject = apps.get_model("learning", "Subject")

    for profile in StudyProfile.objects.all().iterator():
        subject_count = Subject.objects.filter(
            user_id=profile.user_id
        ).count()

        workspace_data = profile.user.workspace_data or "{}"

        try:
            workspace = json.loads(workspace_data)
        except (TypeError, ValueError, json.JSONDecodeError):
            workspace = {}

        if isinstance(workspace, dict):
            session_profile = workspace.get("onboarding_profile")

            if isinstance(session_profile, dict):
                try:
                    planned_count = int(
                        session_profile.get("subject_count")
                    )
                except (TypeError, ValueError):
                    planned_count = None

                if planned_count is not None and 0 <= planned_count <= 20:
                    subject_count = max(subject_count, planned_count)

        profile.subject_count = min(subject_count, 20)
        profile.save(update_fields=["subject_count"])


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0005_migrate_workspace_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="studyprofile",
            name="subject_count",
            field=models.PositiveSmallIntegerField(
                default=0,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(20),
                ],
            ),
        ),
        migrations.RunPython(
            populate_subject_count,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

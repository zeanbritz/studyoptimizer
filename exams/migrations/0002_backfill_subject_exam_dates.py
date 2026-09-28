from django.db import migrations


def backfill_subject_exams(apps, schema_editor):
    Subject = apps.get_model("learning", "Subject")
    AssessmentEvent = apps.get_model("exams", "AssessmentEvent")
    database = schema_editor.connection.alias

    for subject in Subject.objects.using(database).exclude(exam_date__isnull=True).iterator():
        matching_event = AssessmentEvent.objects.using(database).filter(
            subject_id=subject.pk,
            date=subject.exam_date,
            kind="exam",
        ).exists()
        if not matching_event:
            AssessmentEvent.objects.using(database).create(
                subject_id=subject.pk,
                date=subject.exam_date,
                kind="exam",
            )


class Migration(migrations.Migration):
    dependencies = [
        ("exams", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            backfill_subject_exams,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

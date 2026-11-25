from itertools import islice

from django.db import migrations, models


def preserve_correct_answers(apps, schema_editor):
    questions = apps.get_model("questions", "Question").objects.using(schema_editor.connection.alias)
    rows = questions.only("correct_index").iterator(chunk_size=500)
    while batch := list(islice(rows, 500)):
        for question in batch:
            question.correct_indices = [question.correct_index]
        questions.bulk_update(batch, ["correct_indices"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("questions", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="question",
            name="correct_indices",
            field=models.JSONField(default=list),
            preserve_default=False,
        ),
        migrations.RunPython(preserve_correct_answers),
        migrations.RemoveField(model_name="question", name="correct_index"),
    ]

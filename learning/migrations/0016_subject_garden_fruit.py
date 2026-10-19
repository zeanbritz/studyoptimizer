from django.db import migrations, models


FRUITS = ["red-apple", "pear", "peach", "green-apple", "yellow-apple", "red-pear"]


def assign_fruits(apps, schema_editor):
    Subject = apps.get_model("learning", "Subject")
    previous_user = None
    index = 0
    for subject in Subject.objects.using(schema_editor.connection.alias).order_by("user_id", "created", "pk").iterator():
        if subject.user_id != previous_user:
            previous_user, index = subject.user_id, 0
        Subject.objects.using(schema_editor.connection.alias).filter(pk=subject.pk).update(garden_fruit=FRUITS[index % len(FRUITS)])
        index += 1


class Migration(migrations.Migration):
    dependencies = [("learning", "0015_definition_book_name_definition_chapter")]

    operations = [
        migrations.AddField(
            model_name="subject", name="garden_fruit",
            field=models.CharField(blank=True, choices=[("red-apple", "Red apple"), ("pear", "Pear"), ("peach", "Peach"), ("green-apple", "Green apple"), ("yellow-apple", "Yellow apple"), ("red-pear", "Red pear")], editable=False, max_length=16),
        ),
        migrations.RunPython(assign_fruits, migrations.RunPython.noop),
    ]

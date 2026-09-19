from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_user_workspace_data"),
        ("dashboard", "0006_studyprofile_subject_count"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="workspace_data",
        ),
    ]

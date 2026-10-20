import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0009_studyprofile_subject_tour_completed")]

    operations = [
        migrations.AlterField(
            model_name="studyprofile",
            name="subject_count",
            field=models.PositiveIntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)]),
        ),
    ]

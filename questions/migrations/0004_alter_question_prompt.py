from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("questions", "0003_questionimage")]

    operations = [
        migrations.AlterField(
            model_name="question",
            name="prompt",
            field=models.TextField(max_length=10000),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cases", "0002_case_workflow_dimensions"),
    ]

    operations = [
        migrations.AddField(
            model_name="case",
            name="case_type_key",
            field=models.CharField(blank=True, db_index=True, max_length=96),
        ),
    ]

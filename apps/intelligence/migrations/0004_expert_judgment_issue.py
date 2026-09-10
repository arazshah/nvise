from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("intelligence", "0003_issue_resolution_workflow"),
    ]

    operations = [
        migrations.AlterField(
            model_name="casefieldissue",
            name="issue_type",
            field=models.CharField(
                choices=[
                    ("missing", "Missing"),
                    ("conflict", "Conflict"),
                    ("invalid", "Invalid"),
                    ("expert_judgment", "Expert judgment"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]

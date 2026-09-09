from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("processing", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="processingjob",
            constraint=models.UniqueConstraint(
                fields=("attachment", "job_type"),
                name="uniq_attachment_job_type",
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("intelligence", "0002_followupquestion")]

    operations = [
        migrations.AlterField(
            model_name="casefieldissue",
            name="status",
            field=models.CharField(
                choices=[
                    ("open", "باز"),
                    ("resolved", "رفع شده"),
                    ("unavailable", "اطلاعات در دسترس نیست"),
                    ("waived", "با اطلاعات فعلی ادامه داده شود"),
                ],
                db_index=True,
                default="open",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="casefieldissue",
            name="attempt_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="casefieldissue",
            name="resolution_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddConstraint(
            model_name="casefieldissue",
            constraint=models.UniqueConstraint(
                fields=("case", "field", "issue_type"),
                condition=models.Q(status="open"),
                name="uniq_open_case_field_issue",
            ),
        ),
    ]

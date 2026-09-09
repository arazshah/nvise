from django.db import migrations, models
from django.db.models import Count


def deduplicate_open_case_field_issues(apps, schema_editor):
    CaseFieldIssue = apps.get_model("intelligence", "CaseFieldIssue")

    duplicate_groups = (
        CaseFieldIssue.objects.filter(status="open")
        .values("case_id", "field_id", "issue_type")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )

    for group in duplicate_groups.iterator():
        issues = list(
            CaseFieldIssue.objects.filter(
                status="open",
                case_id=group["case_id"],
                field_id=group["field_id"],
                issue_type=group["issue_type"],
            ).order_by("created_at", "id")
        )
        if len(issues) < 2:
            continue

        keeper = issues[0]
        duplicates = issues[1:]

        max_attempt_count = max((getattr(issue, "attempt_count", 0) or 0) for issue in issues)
        if getattr(keeper, "attempt_count", 0) != max_attempt_count:
            keeper.attempt_count = max_attempt_count
            keeper.save(update_fields=["attempt_count"])

        CaseFieldIssue.objects.filter(id__in=[issue.id for issue in duplicates]).delete()


def noop_reverse(apps, schema_editor):
    pass


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
        migrations.RunPython(
            deduplicate_open_case_field_issues,
            noop_reverse,
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

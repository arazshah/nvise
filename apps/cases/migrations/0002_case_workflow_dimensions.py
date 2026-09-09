from django.db import migrations, models


def populate_workflow_states(apps, schema_editor):
    Case = apps.get_model("cases", "Case")
    for case in Case.objects.all().iterator():
        lifecycle = "active"
        analysis = "not_started"
        report = "not_created"

        if case.status == "archived":
            lifecycle = "archived"
        elif case.status == "cancelled":
            lifecycle = "cancelled"

        if case.status == "finalizing":
            analysis = "processing"
        elif case.status == "needs_information":
            analysis = "needs_review"
        elif case.status in {"ready_for_review", "approved", "archived"}:
            analysis = "completed"

        if case.status == "ready_for_review":
            report = "ready_for_review"
        elif case.status in {"approved", "archived"}:
            report = "approved"

        Case.objects.filter(pk=case.pk).update(
            lifecycle_status=lifecycle,
            analysis_status=analysis,
            report_status=report,
        )


class Migration(migrations.Migration):
    dependencies = [("cases", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="case",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "پیش‌نویس"),
                    ("open", "در حال جمع‌آوری اطلاعات"),
                    ("finalizing", "در حال تحلیل"),
                    ("needs_information", "نیازمند بررسی اطلاعات"),
                    ("ready_for_review", "آماده بررسی گزارش"),
                    ("approved", "تأیید شده"),
                    ("archived", "بایگانی شده"),
                    ("cancelled", "لغو شده"),
                ],
                db_index=True,
                default="draft",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="case",
            name="lifecycle_status",
            field=models.CharField(
                choices=[
                    ("active", "فعال"),
                    ("archived", "بایگانی شده"),
                    ("cancelled", "لغو شده"),
                ],
                db_index=True,
                default="active",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="case",
            name="analysis_status",
            field=models.CharField(
                choices=[
                    ("not_started", "شروع نشده"),
                    ("queued", "در صف تحلیل"),
                    ("processing", "در حال تحلیل"),
                    ("needs_review", "نیازمند بررسی"),
                    ("completed", "تحلیل تکمیل شده"),
                    ("failed", "تحلیل ناموفق"),
                ],
                db_index=True,
                default="not_started",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="case",
            name="report_status",
            field=models.CharField(
                choices=[
                    ("not_created", "ایجاد نشده"),
                    ("draft", "پیش‌نویس"),
                    ("ready_for_review", "آماده بررسی"),
                    ("approved", "تأیید شده"),
                ],
                db_index=True,
                default="not_created",
                max_length=24,
            ),
        ),
        migrations.RunPython(populate_workflow_states, migrations.RunPython.noop),
    ]

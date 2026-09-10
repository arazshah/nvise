import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("intelligence", "0004_expert_judgment_issue"),
    ]

    operations = [
        migrations.CreateModel(
            name="GoldenCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("key", models.SlugField(max_length=96, unique=True)),
                ("name", models.CharField(max_length=180)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("expected_facts", models.JSONField(blank=True, default=dict)),
                ("no_followup_fact_keys", models.JSONField(blank=True, default=list)),
                ("minimum_grounding_ratio", models.FloatField(default=0.9)),
                ("minimum_fact_recall", models.FloatField(default=0.9)),
                ("maximum_redundant_question_rate", models.FloatField(default=0.05)),
                ("expert_report_score", models.FloatField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("case", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="golden_case", to="cases.case")),
            ],
        ),
        migrations.CreateModel(
            name="GoldenCaseEvaluation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("report_revision_id", models.UUIDField(blank=True, null=True)),
                ("status", models.CharField(choices=[("passed", "Passed"), ("failed", "Failed")], db_index=True, max_length=16)),
                ("fact_recall", models.FloatField(default=0)),
                ("exact_fact_accuracy", models.FloatField(default=0)),
                ("redundant_question_rate", models.FloatField(default=0)),
                ("claim_grounding_ratio", models.FloatField(default=0)),
                ("report_quality_score", models.FloatField(blank=True, null=True)),
                ("overall_score", models.FloatField(default=0)),
                ("metrics", models.JSONField(blank=True, default=dict)),
                ("git_sha", models.CharField(blank=True, max_length=64)),
                ("model_name", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("extraction_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="golden_evaluations", to="intelligence.extractionrun")),
                ("golden_case", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evaluations", to="intelligence.goldencase")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]

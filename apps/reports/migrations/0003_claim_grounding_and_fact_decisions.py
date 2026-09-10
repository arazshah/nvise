# Generated manually for Nvise claim-level grounding.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("intelligence", "0004_expert_judgment_issue"),
        ("reports", "0002_reportsectionreview"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ExpertFactDecision",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("decision", models.CharField(choices=[("confirmed", "Confirmed"), ("corrected", "Corrected"), ("rejected", "Rejected")], db_index=True, max_length=24)),
                ("corrected_value", models.JSONField(blank=True, null=True)),
                ("note", models.TextField(blank=True)),
                ("evidence_snapshot", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="expert_fact_decisions", to="cases.case")),
                ("field", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expert_decisions", to="intelligence.fielddefinition")),
                ("reviewer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expert_fact_decisions", to=settings.AUTH_USER_MODEL)),
                ("source_fact", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expert_decisions", to="intelligence.extractedfact")),
            ],
        ),
        migrations.AddConstraint(
            model_name="expertfactdecision",
            constraint=models.UniqueConstraint(fields=("case", "field"), name="uniq_case_authoritative_fact_decision"),
        ),
        migrations.CreateModel(
            name="ReportClaim",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sequence", models.PositiveIntegerField(default=0)),
                ("claim_type", models.CharField(choices=[("fact", "Fact"), ("inference", "Inference"), ("professional_opinion", "Professional opinion"), ("unresolved", "Unresolved")], db_index=True, max_length=32)),
                ("text", models.TextField()),
                ("fact_keys", models.JSONField(blank=True, default=list)),
                ("evidence_snapshot", models.JSONField(blank=True, default=list)),
                ("confidence", models.FloatField(blank=True, null=True)),
                ("revision", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="claims", to="reports.reportrevision")),
                ("section", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="claims", to="reports.reportsection")),
            ],
            options={"ordering": ["section__sequence", "sequence", "id"]},
        ),
        migrations.CreateModel(
            name="ReportClaimReview",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("decision", models.CharField(choices=[("accepted", "Accepted"), ("needs_edit", "Needs edit"), ("rejected", "Rejected")], db_index=True, max_length=24)),
                ("note", models.TextField(blank=True)),
                ("reviewed_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("claim", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reviews", to="reports.reportclaim")),
                ("reviewer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="report_claim_reviews", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="reportclaimreview",
            constraint=models.UniqueConstraint(fields=("claim", "reviewer"), name="uniq_claim_reviewer"),
        ),
    ]

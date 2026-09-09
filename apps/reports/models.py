import uuid

from django.conf import settings
from django.db import models

from apps.cases.models import Case


class Report(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY_FOR_REVIEW = "ready_for_review", "Ready for review"
        APPROVED = "approved", "Approved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.OneToOneField(Case, on_delete=models.CASCADE, related_name="report")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    current_revision = models.ForeignKey(
        "ReportRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for_reports",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ReportRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="revisions")
    revision_number = models.PositiveIntegerField()
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True)
    structured_data = models.JSONField(default=dict, blank=True)
    source_snapshot = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="report_revisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["revision_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["report", "revision_number"],
                name="uniq_report_revision_number",
            )
        ]


class ReportSection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(ReportRevision, on_delete=models.CASCADE, related_name="sections")
    key = models.SlugField(max_length=96)
    title = models.CharField(max_length=180)
    sequence = models.PositiveIntegerField(default=0)
    content = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sequence", "key"]
        constraints = [
            models.UniqueConstraint(fields=["revision", "key"], name="uniq_revision_section_key")
        ]


class ReportApproval(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="approvals")
    revision = models.ForeignKey(ReportRevision, on_delete=models.PROTECT, related_name="approvals")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="report_approvals",
    )
    approved_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

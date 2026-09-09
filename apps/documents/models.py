import uuid

from django.conf import settings
from django.db import models

from apps.reports.models import ReportRevision


class GeneratedDocument(models.Model):
    class Kind(models.TextChoices):
        DOCX = "docx", "DOCX"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RENDERING = "rendering", "Rendering"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(
        ReportRevision,
        on_delete=models.CASCADE,
        related_name="generated_documents",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.DOCX)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    storage_key = models.CharField(max_length=512, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    mime_type = models.CharField(
        max_length=128,
        default="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    filename = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "kind"],
                name="uniq_revision_document_kind",
            )
        ]

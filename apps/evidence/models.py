import uuid

from django.db import models

from apps.cases.models import Case
from apps.messaging.models import CaseMessage
from apps.transcription.models import TranscriptSegment


class Evidence(models.Model):
    class SourceKind(models.TextChoices):
        MESSAGE = "message", "Message"
        TRANSCRIPT_SEGMENT = "transcript_segment", "Transcript segment"
        DOCUMENT_PAGE = "document_page", "Document page"
        IMAGE_ANALYSIS = "image_analysis", "Image analysis"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="evidence_items")
    source_kind = models.CharField(max_length=32, choices=SourceKind.choices, db_index=True)
    message = models.ForeignKey(
        CaseMessage,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="evidence_items",
    )
    transcript_segment = models.ForeignKey(
        TranscriptSegment,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="evidence_items",
    )
    text = models.TextField()
    start_ms = models.PositiveIntegerField(null=True, blank=True)
    end_ms = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["case", "source_kind"], name="evidence_case_source_idx")]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(source_kind="message", message__isnull=False, transcript_segment__isnull=True)
                    | models.Q(
                        source_kind="transcript_segment",
                        message__isnull=True,
                        transcript_segment__isnull=False,
                    )
                    | models.Q(
                        source_kind__in=["document_page", "image_analysis"],
                        message__isnull=False,
                        transcript_segment__isnull=True,
                    )
                ),
                name="evidence_valid_source",
            )
        ]

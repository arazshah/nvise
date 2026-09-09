import uuid

from django.db import models

from apps.processing.models import CaseAttachment, ProcessingJob


class Recording(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        TRANSCRIBING = "transcribing", "Transcribing"
        TRANSCRIBED = "transcribed", "Transcribed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attachment = models.OneToOneField(
        CaseAttachment,
        on_delete=models.CASCADE,
        related_name="recording",
    )
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    sample_rate_hz = models.PositiveIntegerField(null=True, blank=True)
    channels = models.PositiveSmallIntegerField(null=True, blank=True)
    codec = models.CharField(max_length=64, blank=True)
    language_hint = models.CharField(max_length=16, default="fa")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Transcript(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recording = models.ForeignKey(Recording, on_delete=models.CASCADE, related_name="transcripts")
    processing_job = models.OneToOneField(
        ProcessingJob,
        on_delete=models.PROTECT,
        related_name="transcript",
    )
    provider = models.CharField(max_length=64)
    model_name = models.CharField(max_length=128, blank=True)
    language = models.CharField(max_length=16, blank=True)
    text = models.TextField(blank=True)
    confidence = models.FloatField(null=True, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class TranscriptSegment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transcript = models.ForeignKey(Transcript, on_delete=models.CASCADE, related_name="segments")
    sequence = models.PositiveIntegerField()
    start_ms = models.PositiveIntegerField()
    end_ms = models.PositiveIntegerField()
    text = models.TextField()
    confidence = models.FloatField(null=True, blank=True)
    speaker = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["transcript", "sequence"], name="uniq_transcript_segment_sequence")
        ]

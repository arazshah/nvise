import uuid

from django.db import models

from apps.messaging.models import CaseMessage


class CaseAttachment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        FETCHING = "fetching", "Fetching"
        STORED = "stored", "Stored"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.OneToOneField(
        CaseMessage,
        on_delete=models.CASCADE,
        related_name="attachment",
    )
    provider = models.CharField(max_length=32)
    external_file_id = models.CharField(max_length=255)
    original_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=150, blank=True)
    declared_size = models.BigIntegerField(null=True, blank=True)
    actual_size = models.BigIntegerField(null=True, blank=True)
    provider_file_path = models.TextField(blank=True)
    storage_key = models.CharField(max_length=500, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProcessingJob(models.Model):
    class JobType(models.TextChoices):
        FETCH_ATTACHMENT = "fetch_attachment", "Fetch attachment"
        TRANSCRIBE_AUDIO = "transcribe_audio", "Transcribe audio"
        EXTRACT_DOCUMENT = "extract_document", "Extract document"
        ANALYZE_IMAGE = "analyze_image", "Analyze image"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attachment = models.ForeignKey(CaseAttachment, on_delete=models.CASCADE, related_name="jobs")
    job_type = models.CharField(max_length=32, choices=JobType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    priority = models.PositiveSmallIntegerField(default=100)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    available_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["status", "available_at", "priority"])]


class ProcessingAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(ProcessingJob, on_delete=models.CASCADE, related_name="attempt_records")
    attempt_number = models.PositiveSmallIntegerField()
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    succeeded = models.BooleanField(default=False)
    error_class = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "attempt_number"], name="uniq_job_attempt_number")
        ]

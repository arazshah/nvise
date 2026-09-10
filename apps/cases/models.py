import uuid

from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class Case(models.Model):
    class Status(models.TextChoices):
        """Legacy combined workflow status kept for backwards compatibility."""

        DRAFT = "draft", "پیش‌نویس"
        OPEN = "open", "در حال جمع‌آوری اطلاعات"
        FINALIZING = "finalizing", "در حال تحلیل"
        NEEDS_INFORMATION = "needs_information", "نیازمند بررسی اطلاعات"
        READY_FOR_REVIEW = "ready_for_review", "آماده بررسی گزارش"
        APPROVED = "approved", "تأیید شده"
        ARCHIVED = "archived", "بایگانی شده"
        CANCELLED = "cancelled", "لغو شده"

    class LifecycleStatus(models.TextChoices):
        ACTIVE = "active", "فعال"
        ARCHIVED = "archived", "بایگانی شده"
        CANCELLED = "cancelled", "لغو شده"

    class AnalysisStatus(models.TextChoices):
        NOT_STARTED = "not_started", "شروع نشده"
        QUEUED = "queued", "در صف تحلیل"
        PROCESSING = "processing", "در حال تحلیل"
        NEEDS_REVIEW = "needs_review", "نیازمند بررسی"
        COMPLETED = "completed", "تحلیل تکمیل شده"
        FAILED = "failed", "تحلیل ناموفق"

    class ReportStatus(models.TextChoices):
        NOT_CREATED = "not_created", "ایجاد نشده"
        DRAFT = "draft", "پیش‌نویس"
        READY_FOR_REVIEW = "ready_for_review", "آماده بررسی"
        APPROVED = "approved", "تأیید شده"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="cases")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_cases")
    title = models.CharField(max_length=255, blank=True)
    case_code = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    lifecycle_status = models.CharField(
        max_length=16,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.ACTIVE,
        db_index=True,
    )
    analysis_status = models.CharField(
        max_length=16,
        choices=AnalysisStatus.choices,
        default=AnalysisStatus.NOT_STARTED,
        db_index=True,
    )
    report_status = models.CharField(
        max_length=24,
        choices=ReportStatus.choices,
        default=ReportStatus.NOT_CREATED,
        db_index=True,
    )
    vertical_key = models.CharField(max_length=64, blank=True)
    sub_vertical_key = models.CharField(max_length=64, blank=True)
    case_type_key = models.CharField(max_length=96, blank=True, db_index=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.title or self.case_code


class CaseEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=64, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

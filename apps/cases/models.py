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


class CaseAction(models.Model):
    class ActionType(models.TextChoices):
        MANUAL = "manual", "اقدام دستی"
        START_ANALYSIS = "start_analysis", "شروع تحلیل"
        REVIEW_ANALYSIS = "review_analysis", "بررسی تحلیل"
        RETRY_ANALYSIS = "retry_analysis", "بررسی تحلیل ناموفق"
        GENERATE_REPORT = "generate_report", "تولید گزارش"
        REVIEW_REPORT = "review_report", "بررسی گزارش"
        REGENERATE_REPORT = "regenerate_report", "بازسازی گزارش"
        FOLLOW_UP = "follow_up", "پیگیری پرونده"

    class Status(models.TextChoices):
        OPEN = "open", "باز"
        DONE = "done", "انجام شده"
        DISMISSED = "dismissed", "کنار گذاشته شده"

    class Priority(models.IntegerChoices):
        LOW = 10, "کم"
        NORMAL = 20, "عادی"
        HIGH = 30, "مهم"
        URGENT = 40, "فوری"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="actions")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    action_type = models.CharField(max_length=32, choices=ActionType.choices, default=ActionType.MANUAL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.NORMAL, db_index=True)
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    system_key = models.CharField(max_length=96, blank=True)
    source_event = models.CharField(max_length=96, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_case_actions",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "due_at", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["case", "system_key"],
                condition=~models.Q(system_key=""),
                name="uniq_case_system_action",
            )
        ]
        indexes = [
            models.Index(fields=["status", "due_at", "priority"], name="case_action_queue_idx")
        ]

    def __str__(self) -> str:
        return f"{self.case.case_code}: {self.title}"


class ReminderPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reminder_preference",
    )
    reminders_enabled = models.BooleanField(default=True)
    due_action_enabled = models.BooleanField(default=True)
    report_review_enabled = models.BooleanField(default=True)
    stale_case_enabled = models.BooleanField(default=True)
    daily_digest_enabled = models.BooleanField(default=False)
    weekly_digest_enabled = models.BooleanField(default=True)
    quiet_start = models.TimeField(default="22:00")
    quiet_end = models.TimeField(default="08:00")
    updated_at = models.DateTimeField(auto_now=True)


class CaseReminder(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار"
        DISPATCHING = "dispatching", "در حال ارسال"
        SENT = "sent", "ارسال شده"
        CANCELLED = "cancelled", "لغو شده"

    class Channel(models.TextChoices):
        BALE = "bale", "بله"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.ForeignKey(CaseAction, on_delete=models.CASCADE, related_name="reminders")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="case_reminders",
    )
    remind_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.BALE)
    dedupe_key = models.CharField(max_length=160, unique=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["remind_at", "created_at"]
        indexes = [
            models.Index(fields=["status", "remind_at"], name="case_reminder_due_idx")
        ]

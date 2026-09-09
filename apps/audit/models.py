import uuid

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    case = models.ForeignKey(
        "cases.Case",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    event_type = models.CharField(max_length=120, db_index=True)
    object_type = models.CharField(max_length=120, blank=True)
    object_id = models.CharField(max_length=128, blank=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    source = models.CharField(max_length=32, default="system")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "created_at"], name="audit_tenant_time_idx"),
            models.Index(fields=["case", "created_at"], name="audit_case_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.created_at:%Y-%m-%d %H:%M:%S}"

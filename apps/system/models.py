import uuid

from django.db import models


class TaskFailure(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_id = models.CharField(max_length=64, unique=True)
    task_name = models.CharField(max_length=255, db_index=True)
    exception_class = models.CharField(max_length=255, blank=True)
    exception_message = models.TextField(blank=True)
    traceback = models.TextField(blank=True)
    retries = models.PositiveIntegerField(default=0)
    resolved = models.BooleanField(default=False, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.task_name} ({self.task_id})"

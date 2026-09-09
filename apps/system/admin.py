from django.contrib import admin
from django.utils import timezone

from .models import TaskFailure


@admin.register(TaskFailure)
class TaskFailureAdmin(admin.ModelAdmin):
    list_display = ("created_at", "task_name", "task_id", "exception_class", "retries", "resolved")
    list_filter = ("resolved", "task_name", "created_at")
    search_fields = ("task_id", "task_name", "exception_class", "exception_message")
    readonly_fields = (
        "id",
        "task_id",
        "task_name",
        "exception_class",
        "exception_message",
        "traceback",
        "retries",
        "created_at",
        "updated_at",
    )
    actions = ["mark_resolved"]

    @admin.action(description="Mark selected failures as resolved")
    def mark_resolved(self, request, queryset):
        queryset.update(resolved=True, resolved_at=timezone.now())

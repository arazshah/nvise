from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "tenant", "actor", "case", "source", "request_id")
    list_filter = ("event_type", "source", "created_at")
    search_fields = (
        "event_type",
        "tenant__name",
        "tenant__slug",
        "case__case_code",
        "actor__username",
        "request_id",
        "object_id",
    )
    readonly_fields = (
        "id",
        "tenant",
        "actor",
        "case",
        "event_type",
        "object_type",
        "object_id",
        "request_id",
        "source",
        "metadata",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

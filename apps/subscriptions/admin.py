from django.contrib import admin

from .models import Entitlement, PaymentAttempt, Plan, Subscription, UsageRecord


class EntitlementInline(admin.TabularInline):
    model = Entitlement
    extra = 0


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "is_active",
        "monthly_price",
        "currency",
        "max_cases_per_period",
        "max_stt_seconds_per_period",
        "max_ai_extractions_per_period",
        "max_members",
    )
    list_filter = ("is_active", "currency")
    search_fields = ("code", "name")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "tenant",
        "plan",
        "status",
        "current_period_start",
        "current_period_end",
        "cancel_at_period_end",
    )
    list_filter = ("status", "plan", "cancel_at_period_end")
    search_fields = (
        "tenant__name",
        "tenant__slug",
        "external_customer_id",
        "external_subscription_id",
    )
    inlines = [EntitlementInline]


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "tenant",
        "user",
        "plan",
        "amount",
        "currency",
        "status",
        "paid_at",
    )
    list_filter = ("status", "plan", "currency", "created_at")
    search_fields = (
        "tenant__name",
        "tenant__slug",
        "user__username",
        "payload",
        "pre_checkout_query_id",
        "provider_payment_charge_id",
        "provider_tracking_id",
    )
    readonly_fields = (
        "id",
        "tenant",
        "user",
        "plan",
        "provider",
        "status",
        "payload",
        "amount",
        "currency",
        "external_user_id",
        "external_chat_id",
        "invoice_message_id",
        "pre_checkout_query_id",
        "provider_payment_charge_id",
        "provider_tracking_id",
        "failure_reason",
        "raw_precheckout",
        "raw_successful_payment",
        "invoice_sent_at",
        "precheckout_at",
        "paid_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ("tenant", "metric", "quantity", "case", "occurred_at", "idempotency_key")
    list_filter = ("metric", "occurred_at")
    search_fields = ("tenant__name", "tenant__slug", "idempotency_key", "case__case_code")
    readonly_fields = (
        "tenant",
        "metric",
        "quantity",
        "idempotency_key",
        "case",
        "metadata",
        "occurred_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

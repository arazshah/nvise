from asgiref.sync import async_to_sync
import httpx
from django import forms
from django.contrib import admin
from django.utils import timezone

from apps.messaging.providers.bale.client import BaleClient

from .integrations import get_bale_config
from .models import IntegrationSettings, TaskFailure


class IntegrationSettingsForm(forms.ModelForm):
    avalai_api_key = forms.CharField(
        required=False,
        label="AvalAI API Key",
        widget=forms.PasswordInput(render_value=False),
        help_text="برای حفظ کلید فعلی خالی بگذارید. مقدار جدید به‌صورت رمزنگاری‌شده ذخیره می‌شود.",
    )
    bale_bot_token = forms.CharField(
        required=False,
        label="Bale Bot Token",
        widget=forms.PasswordInput(render_value=False),
        help_text="برای حفظ توکن فعلی خالی بگذارید.",
    )
    bale_webhook_secret = forms.CharField(
        required=False,
        label="Bale Webhook Secret",
        widget=forms.PasswordInput(render_value=False),
        help_text="برای حفظ secret فعلی خالی بگذارید.",
    )

    class Meta:
        model = IntegrationSettings
        exclude = (
            "avalai_api_key_encrypted",
            "bale_bot_token_encrypted",
            "bale_webhook_secret_encrypted",
        )

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get("avalai_api_key"):
            instance.set_avalai_api_key(self.cleaned_data["avalai_api_key"])
        if self.cleaned_data.get("bale_bot_token"):
            instance.set_bale_bot_token(self.cleaned_data["bale_bot_token"])
        if self.cleaned_data.get("bale_webhook_secret"):
            instance.set_bale_webhook_secret(self.cleaned_data["bale_webhook_secret"])
        if commit:
            instance.save()
            self.save_m2m()
        return instance


@admin.register(IntegrationSettings)
class IntegrationSettingsAdmin(admin.ModelAdmin):
    form = IntegrationSettingsForm
    list_display = (
        "__str__",
        "avalai_enabled",
        "avalai_text_model",
        "avalai_stt_model",
        "bale_enabled",
        "avalai_configured",
        "bale_configured",
        "updated_at",
    )
    readonly_fields = (
        "avalai_configured",
        "bale_configured",
        "bale_webhook_url",
        "last_avalai_test_at",
        "last_avalai_test_ok",
        "last_avalai_test_message",
        "last_bale_test_at",
        "last_bale_test_ok",
        "last_bale_test_message",
        "last_bale_webhook_at",
        "updated_at",
    )
    actions = ("test_avalai", "test_bale", "register_bale_webhook")
    fieldsets = (
        ("AvalAI", {
            "fields": (
                "avalai_enabled",
                "avalai_base_url",
                "avalai_api_key",
                "avalai_configured",
                "avalai_text_model",
                "avalai_stt_model",
                "avalai_stt_language",
                "avalai_timeout_seconds",
            )
        }),
        ("AvalAI status", {
            "fields": (
                "last_avalai_test_at",
                "last_avalai_test_ok",
                "last_avalai_test_message",
            )
        }),
        ("Bale messenger", {
            "fields": (
                "bale_enabled",
                "bale_bot_id",
                "bale_public_url",
                "bale_bot_token",
                "bale_webhook_secret",
                "bale_webhook_rate_limit_per_minute",
                "bale_configured",
                "bale_webhook_url",
            )
        }),
        ("Bale status", {
            "fields": (
                "last_bale_test_at",
                "last_bale_test_ok",
                "last_bale_test_message",
                "last_bale_webhook_at",
            )
        }),
        ("System", {"fields": ("updated_at",)}),
    )

    def has_add_permission(self, request):
        return not IntegrationSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(boolean=True, description="AvalAI key configured")
    def avalai_configured(self, obj):
        return bool(obj and obj.avalai_api_key)

    @admin.display(boolean=True, description="Bale token/secret configured")
    def bale_configured(self, obj):
        return bool(obj and obj.bale_bot_token and obj.bale_webhook_secret)

    @admin.display(description="Webhook URL")
    def bale_webhook_url(self, obj):
        return get_bale_config().webhook_url if obj else ""

    @admin.action(description="Test AvalAI text connection")
    def test_avalai(self, request, queryset):
        for obj in queryset:
            try:
                key = obj.avalai_api_key
                if not key:
                    raise RuntimeError("AvalAI API Key تنظیم نشده است")
                response = httpx.post(
                    f"{obj.avalai_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": obj.avalai_text_model,
                        "messages": [{"role": "user", "content": "Reply only with OK"}],
                        "max_tokens": 16,
                    },
                    timeout=obj.avalai_timeout_seconds,
                )
                response.raise_for_status()
                trace = response.headers.get("avalai-request-id", "")
                obj.last_avalai_test_ok = True
                obj.last_avalai_test_message = f"Connected successfully. avalai-request-id={trace}"[:500]
                self.message_user(request, "اتصال AvalAI موفق بود.")
            except Exception as exc:
                obj.last_avalai_test_ok = False
                obj.last_avalai_test_message = str(exc)[:500]
                self.message_user(request, f"خطای AvalAI: {exc}", level="ERROR")
            obj.last_avalai_test_at = timezone.now()
            obj.save(update_fields=["last_avalai_test_ok", "last_avalai_test_message", "last_avalai_test_at", "updated_at"])

    @admin.action(description="Test Bale bot connection")
    def test_bale(self, request, queryset):
        for obj in queryset:
            try:
                token = obj.bale_bot_token
                if not token:
                    raise RuntimeError("Bale Bot Token تنظیم نشده است")
                result = async_to_sync(BaleClient(token).call)("getMe") or {}
                name = result.get("username") or result.get("first_name") or result.get("id") or "bot"
                obj.last_bale_test_ok = True
                obj.last_bale_test_message = f"Connected to {name}"[:500]
                self.message_user(request, f"اتصال بله موفق بود: {name}")
            except Exception as exc:
                obj.last_bale_test_ok = False
                obj.last_bale_test_message = str(exc)[:500]
                self.message_user(request, f"خطای بله: {exc}", level="ERROR")
            obj.last_bale_test_at = timezone.now()
            obj.save(update_fields=["last_bale_test_ok", "last_bale_test_message", "last_bale_test_at", "updated_at"])

    @admin.action(description="Register / refresh Bale webhook")
    def register_bale_webhook(self, request, queryset):
        for obj in queryset:
            try:
                token = obj.bale_bot_token
                secret = obj.bale_webhook_secret
                if not token or not secret:
                    raise RuntimeError("Bale Bot Token و Webhook Secret باید تنظیم شوند")
                url = get_bale_config().webhook_url
                async_to_sync(BaleClient(token).call)("setWebhook", {"url": url})
                obj.last_bale_webhook_at = timezone.now()
                obj.save(update_fields=["last_bale_webhook_at", "updated_at"])
                self.message_user(request, f"Webhook بله ثبت شد: {url}")
            except Exception as exc:
                self.message_user(request, f"ثبت webhook ناموفق بود: {exc}", level="ERROR")


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

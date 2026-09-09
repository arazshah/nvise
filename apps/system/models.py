import base64
import hashlib
import uuid

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _cipher() -> Fernet:
    raw = getattr(settings, "NVISE_CONFIG_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt(value: str) -> str:
    if not value:
        return ""
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


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


class IntegrationSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    avalai_enabled = models.BooleanField(default=True)
    avalai_base_url = models.URLField(default="https://api.avalai.ir/v1")
    avalai_text_model = models.CharField(max_length=128, default="gpt-5.6-luna")
    avalai_stt_model = models.CharField(max_length=128, default="gpt-4o-mini-transcribe")
    avalai_stt_language = models.CharField(max_length=16, default="fa")
    avalai_timeout_seconds = models.PositiveIntegerField(default=120)
    avalai_api_key_encrypted = models.TextField(blank=True, editable=False)

    bale_enabled = models.BooleanField(default=True)
    bale_bot_id = models.CharField(max_length=128, default="primary")
    bale_public_url = models.URLField(
        blank=True,
        help_text="لینک عمومی ربات بله برای دکمه شروع در صفحه اصلی سایت.",
    )
    bale_bot_token_encrypted = models.TextField(blank=True, editable=False)
    bale_webhook_secret_encrypted = models.TextField(blank=True, editable=False)
    bale_webhook_rate_limit_per_minute = models.PositiveIntegerField(default=120)

    last_avalai_test_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_avalai_test_ok = models.BooleanField(null=True, editable=False)
    last_avalai_test_message = models.CharField(max_length=500, blank=True, editable=False)
    last_bale_test_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_bale_test_ok = models.BooleanField(null=True, editable=False)
    last_bale_test_message = models.CharField(max_length=500, blank=True, editable=False)
    last_bale_webhook_at = models.DateTimeField(null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Integration settings"
        verbose_name_plural = "Integration settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return None

    def __str__(self) -> str:
        return "AvalAI & Bale integrations"

    @property
    def avalai_api_key(self) -> str:
        return _decrypt(self.avalai_api_key_encrypted)

    def set_avalai_api_key(self, value: str) -> None:
        self.avalai_api_key_encrypted = _encrypt(value)

    @property
    def bale_bot_token(self) -> str:
        return _decrypt(self.bale_bot_token_encrypted)

    def set_bale_bot_token(self, value: str) -> None:
        self.bale_bot_token_encrypted = _encrypt(value)

    @property
    def bale_webhook_secret(self) -> str:
        return _decrypt(self.bale_webhook_secret_encrypted)

    def set_bale_webhook_secret(self, value: str) -> None:
        self.bale_webhook_secret_encrypted = _encrypt(value)

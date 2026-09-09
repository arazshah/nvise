from dataclasses import dataclass

from django.conf import settings
from django.db import OperationalError, ProgrammingError

from .models import IntegrationSettings


@dataclass(frozen=True)
class AvalAIConfig:
    enabled: bool
    base_url: str
    api_key: str
    text_model: str
    stt_model: str
    stt_language: str
    timeout_seconds: float


@dataclass(frozen=True)
class BaleConfig:
    enabled: bool
    bot_token: str
    bot_id: str
    webhook_secret: str
    rate_limit_per_minute: int
    webhook_url: str


def _row() -> IntegrationSettings | None:
    try:
        return IntegrationSettings.objects.filter(pk=1).first()
    except (OperationalError, ProgrammingError):
        return None


def get_avalai_config() -> AvalAIConfig:
    row = _row()
    if row and row.avalai_enabled:
        return AvalAIConfig(
            enabled=True,
            base_url=row.avalai_base_url.rstrip("/"),
            api_key=row.avalai_api_key or settings.AI_EXTRACTION_API_KEY or settings.STT_API_KEY,
            text_model=row.avalai_text_model,
            stt_model=row.avalai_stt_model,
            stt_language=row.avalai_stt_language,
            timeout_seconds=float(row.avalai_timeout_seconds),
        )
    return AvalAIConfig(
        enabled=False,
        base_url="https://api.avalai.ir/v1",
        api_key=settings.AI_EXTRACTION_API_KEY or settings.STT_API_KEY,
        text_model="gpt-5.6-luna",
        stt_model="gpt-4o-mini-transcribe",
        stt_language="fa",
        timeout_seconds=float(max(settings.AI_EXTRACTION_TIMEOUT_SECONDS, settings.STT_TIMEOUT_SECONDS)),
    )


def get_bale_config() -> BaleConfig:
    row = _row()
    if row and row.bale_enabled:
        secret = row.bale_webhook_secret or settings.BALE_WEBHOOK_SECRET
        token = row.bale_bot_token or settings.BALE_BOT_TOKEN
        bot_id = row.bale_bot_id or settings.BALE_BOT_ID
        rate_limit = row.bale_webhook_rate_limit_per_minute
    else:
        secret = settings.BALE_WEBHOOK_SECRET
        token = settings.BALE_BOT_TOKEN
        bot_id = settings.BALE_BOT_ID
        rate_limit = settings.BALE_WEBHOOK_RATE_LIMIT_PER_MINUTE
    base = settings.WEB_BASE_URL.rstrip("/")
    webhook_url = f"{base}/webhooks/bale/{secret}/" if secret else ""
    return BaleConfig(
        enabled=bool(row.bale_enabled) if row else True,
        bot_token=token,
        bot_id=bot_id,
        webhook_secret=secret,
        rate_limit_per_minute=rate_limit,
        webhook_url=webhook_url,
    )

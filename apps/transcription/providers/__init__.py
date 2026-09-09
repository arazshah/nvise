from django.conf import settings

from apps.system.integrations import get_avalai_config

from .avalai import AvalAISTTProvider
from .base import STTResult, STTSegment, SpeechToTextProvider
from .http import HTTPSTTProvider


def get_stt_provider() -> SpeechToTextProvider:
    avalai = get_avalai_config()
    if avalai.enabled:
        return AvalAISTTProvider(
            base_url=avalai.base_url,
            api_key=avalai.api_key,
            model=avalai.stt_model,
            language=avalai.stt_language,
            timeout=avalai.timeout_seconds,
        )

    provider = settings.STT_PROVIDER.lower().strip()
    if provider == "http":
        return HTTPSTTProvider(
            endpoint=settings.STT_HTTP_ENDPOINT,
            api_key=settings.STT_API_KEY,
            timeout=settings.STT_TIMEOUT_SECONDS,
        )
    raise RuntimeError(f"Unsupported STT provider: {settings.STT_PROVIDER}")


__all__ = [
    "AvalAISTTProvider",
    "HTTPSTTProvider",
    "STTResult",
    "STTSegment",
    "SpeechToTextProvider",
    "get_stt_provider",
]

from django.conf import settings

from .base import STTResult, STTSegment, SpeechToTextProvider
from .http import HTTPSTTProvider


def get_stt_provider() -> SpeechToTextProvider:
    provider = settings.STT_PROVIDER.lower().strip()
    if provider == "http":
        return HTTPSTTProvider(
            endpoint=settings.STT_HTTP_ENDPOINT,
            api_key=settings.STT_API_KEY,
            timeout=settings.STT_TIMEOUT_SECONDS,
        )
    raise RuntimeError(f"Unsupported STT provider: {settings.STT_PROVIDER}")


__all__ = [
    "HTTPSTTProvider",
    "STTResult",
    "STTSegment",
    "SpeechToTextProvider",
    "get_stt_provider",
]

import logging
from typing import Any

import httpx

from .base import STTResult, STTSegment, SpeechToTextProvider

logger = logging.getLogger(__name__)


class AvalAISTTProvider(SpeechToTextProvider):
    key = "avalai"

    def __init__(self, *, base_url: str, api_key: str, model: str, language: str = "fa", timeout: float = 120.0) -> None:
        if not api_key:
            raise RuntimeError("AvalAI API Key is required")
        self.endpoint = f"{base_url.rstrip('/')}/audio/transcriptions"
        self.api_key = api_key
        self.model = model
        self.language = language
        self.timeout = timeout

    def transcribe(self, *, content: bytes, filename: str, mime_type: str, language_hint: str | None = None) -> STTResult:
        files = {"file": (filename, content, mime_type or "application/octet-stream")}
        data = {
            "model": self.model,
            "language": language_hint or self.language,
            "response_format": "verbose_json",
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=data,
                files=files,
            )
            response.raise_for_status()
            trace = response.headers.get("avalai-request-id", "")
            if trace:
                logger.info("AvalAI STT completed avalai-request-id=%s", trace)
            payload: dict[str, Any] = response.json()

        segments = []
        for item in payload.get("segments") or []:
            start_ms = int(float(item.get("start", 0)) * 1000)
            end_ms = int(float(item.get("end", item.get("start", 0))) * 1000)
            segments.append(
                STTSegment(
                    start_ms=max(0, start_ms),
                    end_ms=max(0, end_ms),
                    text=str(item.get("text") or "").strip(),
                    confidence=item.get("confidence"),
                    speaker=str(item.get("speaker") or ""),
                )
            )
        return STTResult(
            text=str(payload.get("text") or "").strip(),
            language=str(payload.get("language") or language_hint or self.language),
            confidence=payload.get("confidence"),
            model_name=self.model,
            segments=segments,
            raw=payload,
        )

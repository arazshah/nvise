import logging
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from .base import STTResult, STTSegment, SpeechToTextProvider

logger = logging.getLogger(__name__)


_AUDIO_EXTENSIONS = {
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".mp4",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/flac": ".flac",
}


def _normalized_audio_filename(filename: str, mime_type: str) -> str:
    candidate = Path(filename or "recording").name
    suffix = Path(candidate).suffix.lower()
    if suffix and suffix != ".bin":
        return candidate

    normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    extension = _AUDIO_EXTENSIONS.get(normalized_mime)
    if not extension and normalized_mime:
        extension = mimetypes.guess_extension(normalized_mime, strict=False)
    extension = extension or ".ogg"
    stem = Path(candidate).stem if candidate else "recording"
    if stem in {"", ".", "recording.bin"}:
        stem = "recording"
    return f"{stem}{extension}"


def _response_format_for_model(model: str) -> str:
    normalized = (model or "").lower()
    if "diarize" in normalized:
        return "diarized_json"
    if normalized == "whisper-1" or "whisper" in normalized:
        return "verbose_json"
    return "json"


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
        upload_name = _normalized_audio_filename(filename, mime_type)
        upload_mime = (mime_type or "application/octet-stream").split(";", 1)[0].strip()
        files = {"file": (upload_name, content, upload_mime)}
        data = {
            "model": self.model,
            "language": language_hint or self.language,
            "response_format": _response_format_for_model(self.model),
        }
        if "diarize" in (self.model or "").lower():
            data["chunking_strategy"] = "auto"

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=data,
                files=files,
            )
            trace = response.headers.get("avalai-request-id", "")
            if response.is_error:
                body = response.text[:2000]
                logger.error(
                    "AvalAI STT failed status=%s model=%s filename=%s mime=%s avalai-request-id=%s body=%s",
                    response.status_code,
                    self.model,
                    upload_name,
                    upload_mime,
                    trace,
                    body,
                )
                raise RuntimeError(
                    f"AvalAI STT returned HTTP {response.status_code}: {body or response.reason_phrase}"
                )
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

from typing import Any

import httpx

from .base import STTResult, STTSegment, SpeechToTextProvider


class HTTPSTTProvider(SpeechToTextProvider):
    key = "http"

    def __init__(self, *, endpoint: str, api_key: str = "", timeout: float = 120.0) -> None:
        if not endpoint:
            raise ValueError("STT endpoint is required")
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout

    def transcribe(
        self,
        *,
        content: bytes,
        filename: str,
        mime_type: str,
        language_hint: str | None = None,
    ) -> STTResult:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = {}
        if language_hint:
            data["language"] = language_hint

        files = {"file": (filename, content, mime_type or "application/octet-stream")}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.endpoint, headers=headers, data=data, files=files)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()

        raw_segments = payload.get("segments") or []
        segments = []
        for item in raw_segments:
            start_ms = item.get("start_ms")
            end_ms = item.get("end_ms")
            if start_ms is None and item.get("start") is not None:
                start_ms = int(float(item["start"]) * 1000)
            if end_ms is None and item.get("end") is not None:
                end_ms = int(float(item["end"]) * 1000)
            segments.append(
                STTSegment(
                    start_ms=max(0, int(start_ms or 0)),
                    end_ms=max(0, int(end_ms or start_ms or 0)),
                    text=str(item.get("text") or "").strip(),
                    confidence=item.get("confidence"),
                    speaker=str(item.get("speaker") or ""),
                )
            )

        return STTResult(
            text=str(payload.get("text") or "").strip(),
            language=str(payload.get("language") or language_hint or ""),
            confidence=payload.get("confidence"),
            model_name=str(payload.get("model") or payload.get("model_name") or ""),
            segments=segments,
            raw=payload,
        )

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class STTSegment:
    start_ms: int
    end_ms: int
    text: str
    confidence: float | None = None
    speaker: str = ""


@dataclass(slots=True)
class STTResult:
    text: str
    language: str = ""
    confidence: float | None = None
    model_name: str = ""
    segments: list[STTSegment] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class SpeechToTextProvider(ABC):
    key: str

    @abstractmethod
    def transcribe(
        self,
        *,
        content: bytes,
        filename: str,
        mime_type: str,
        language_hint: str | None = None,
    ) -> STTResult:
        raise NotImplementedError

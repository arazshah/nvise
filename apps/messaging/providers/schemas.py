from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


MessageType = Literal["text", "voice", "audio", "image", "document", "location", "unknown"]


@dataclass(frozen=True, slots=True)
class NormalizedFile:
    file_id: str
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


@dataclass(frozen=True, slots=True)
class NormalizedMessage:
    provider: str
    external_user_id: str
    external_chat_id: str
    external_message_id: str
    message_type: MessageType
    sent_at: datetime | None
    text: str | None = None
    file: NormalizedFile | None = None
    latitude: float | None = None
    longitude: float | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class NormalizedUpdate:
    provider: str
    update_id: str
    message: NormalizedMessage | None
    callback_query_id: str | None = None
    callback_data: str | None = None
    raw: dict[str, Any] | None = None

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from ..base import MessagingProvider
from ..schemas import NormalizedFile, NormalizedMessage, NormalizedUpdate
from .client import BaleClient


PORTAL_LOGIN_LABEL = "🌐 ورود به پنل نویسه"
BILLING_LABEL = "💳 اشتراک و مصرف"


class BaleProvider(MessagingProvider):
    key = "bale"

    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self.client = BaleClient(token) if token else None

    def parse_update(self, payload: dict[str, Any]) -> NormalizedUpdate:
        update_id = str(payload.get("update_id", ""))
        message_payload = payload.get("message") or payload.get("edited_message")
        callback = payload.get("callback_query") or {}

        message = self._parse_message(message_payload) if message_payload else None

        if message is None and callback.get("message"):
            message = self._parse_message(callback["message"])

        return NormalizedUpdate(
            provider=self.key,
            update_id=update_id,
            message=message,
            callback_query_id=str(callback.get("id")) if callback.get("id") is not None else None,
            callback_data=callback.get("data"),
            raw=payload,
        )

    def _parse_message(self, payload: dict[str, Any]) -> NormalizedMessage:
        sender = payload.get("from") or {}
        chat = payload.get("chat") or {}
        message_type = "unknown"
        text = payload.get("text") or payload.get("caption")
        file = None
        latitude = None
        longitude = None

        if payload.get("voice"):
            message_type = "voice"
            file = self._parse_file(payload["voice"])
        elif payload.get("audio"):
            message_type = "audio"
            file = self._parse_file(payload["audio"])
        elif payload.get("document"):
            message_type = "document"
            file = self._parse_file(payload["document"])
        elif payload.get("photo"):
            message_type = "image"
            photos = payload["photo"]
            if isinstance(photos, list) and photos:
                file = self._parse_file(photos[-1])
        elif payload.get("location"):
            message_type = "location"
            location = payload["location"]
            latitude = location.get("latitude")
            longitude = location.get("longitude")
        elif payload.get("text") is not None:
            message_type = "text"

        sent_at = None
        if payload.get("date") is not None:
            sent_at = datetime.fromtimestamp(int(payload["date"]), tz=timezone.utc)

        return NormalizedMessage(
            provider=self.key,
            external_user_id=str(sender.get("id", "")),
            external_chat_id=str(chat.get("id", "")),
            external_message_id=str(payload.get("message_id", "")),
            message_type=message_type,
            sent_at=sent_at,
            text=text,
            file=file,
            latitude=latitude,
            longitude=longitude,
            raw=payload,
        )

    @staticmethod
    def _parse_file(payload: dict[str, Any]) -> NormalizedFile:
        return NormalizedFile(
            file_id=str(payload.get("file_id", "")),
            file_name=payload.get("file_name"),
            mime_type=payload.get("mime_type"),
            file_size=payload.get("file_size"),
        )

    @staticmethod
    def _with_portal_button(keyboard: dict | None) -> dict | None:
        if not keyboard or keyboard.get("one_time_keyboard"):
            return keyboard
        rows = deepcopy(keyboard.get("keyboard") or [])
        existing = {
            button.get("text")
            for row in rows
            for button in row
            if isinstance(button, dict)
        }
        if BILLING_LABEL not in existing:
            rows.append([{"text": BILLING_LABEL}])
        if PORTAL_LOGIN_LABEL not in existing:
            rows.append([{"text": PORTAL_LOGIN_LABEL}])
        result = deepcopy(keyboard)
        result["keyboard"] = rows
        return result

    def _require_client(self) -> BaleClient:
        if self.client is None:
            raise RuntimeError("Bale provider requires a token for outbound API calls")
        return self.client

    async def send_text(self, chat_id: str, text: str, keyboard: dict | None = None) -> dict:
        return await self._require_client().send_message(
            chat_id,
            text,
            self._with_portal_button(keyboard),
        )

    async def send_document(
        self,
        chat_id: str,
        document: bytes,
        filename: str,
        caption: str | None = None,
    ) -> dict:
        return await self._require_client().send_document(chat_id, document, filename, caption)

    async def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        await self._require_client().answer_callback_query(callback_id, text)

    async def get_file(self, file_id: str) -> dict:
        return await self._require_client().get_file(file_id)

    def file_download_url(self, file_path: str) -> str:
        if not self.token:
            raise RuntimeError("Bale provider requires a token to build download URLs")
        return f"https://tapi.bale.ai/file/bot{self.token}/{file_path.lstrip('/')}"

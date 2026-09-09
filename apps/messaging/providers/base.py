from abc import ABC, abstractmethod
from typing import Any

from .schemas import NormalizedUpdate


class MessagingProvider(ABC):
    key: str

    @abstractmethod
    def parse_update(self, payload: dict[str, Any]) -> NormalizedUpdate:
        raise NotImplementedError

    @abstractmethod
    async def send_text(self, chat_id: str, text: str, keyboard: dict | None = None) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def send_document(
        self,
        chat_id: str,
        document: bytes,
        filename: str,
        caption: str | None = None,
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_file(self, file_id: str) -> dict:
        raise NotImplementedError

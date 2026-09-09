from typing import Any

import httpx


class BaleAPIError(RuntimeError):
    pass


class BaleClient:
    def __init__(self, token: str, timeout: float = 20.0) -> None:
        self.token = token
        self.base_url = f"https://tapi.bale.ai/bot{token}"
        self.timeout = timeout

    async def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/{method}", json=payload or {})
            response.raise_for_status()
            data = response.json()

        if not data.get("ok"):
            raise BaleAPIError(data.get("description") or f"Bale API call failed: {method}")

        return data.get("result")

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = await self.call("sendMessage", payload)
        return result or {}

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        await self.call("answerCallbackQuery", payload)

    async def get_file(self, file_id: str) -> dict[str, Any]:
        result = await self.call("getFile", {"file_id": file_id})
        return result or {}

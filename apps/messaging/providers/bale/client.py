from typing import Any

import httpx


class BaleAPIError(RuntimeError):
    pass


class BaleFileTooLargeError(BaleAPIError):
    pass


class BaleClient:
    def __init__(self, token: str, timeout: float = 20.0) -> None:
        self.token = token
        self.base_url = f"https://tapi.bale.ai/bot{token}"
        self.file_base_url = f"https://tapi.bale.ai/file/bot{token}"
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

    async def send_invoice(
        self,
        *,
        chat_id: str,
        title: str,
        description: str,
        payload: str,
        provider_token: str,
        prices: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result = await self.call(
            "sendInvoice",
            {
                "chat_id": chat_id,
                "title": title,
                "description": description,
                "payload": payload,
                "provider_token": provider_token,
                "prices": prices,
            },
        )
        return result or {}

    async def answer_pre_checkout_query(
        self,
        *,
        pre_checkout_query_id: str,
        ok: bool,
        error_message: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "pre_checkout_query_id": pre_checkout_query_id,
            "ok": ok,
        }
        if not ok and error_message:
            payload["error_message"] = error_message
        await self.call("answerPreCheckoutQuery", payload)

    async def send_document(
        self,
        chat_id: str,
        document: bytes,
        filename: str,
        caption: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, str] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        files = {
            "document": (
                filename,
                document,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        async with httpx.AsyncClient(timeout=max(self.timeout, 60.0)) as client:
            response = await client.post(f"{self.base_url}/sendDocument", data=data, files=files)
            response.raise_for_status()
            payload = response.json()
        if not payload.get("ok"):
            raise BaleAPIError(payload.get("description") or "Bale sendDocument failed")
        return payload.get("result") or {}

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        await self.call("answerCallbackQuery", payload)

    async def get_file(self, file_id: str) -> dict[str, Any]:
        result = await self.call("getFile", {"file_id": file_id})
        return result or {}

    async def download_file(self, file_path: str, max_bytes: int) -> bytes:
        url = f"{self.file_base_url}/{file_path.lstrip('/')}"
        chunks: list[bytes] = []
        total = 0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    raise BaleFileTooLargeError(
                        f"Bale file exceeds maximum allowed size ({content_length} > {max_bytes})"
                    )

                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise BaleFileTooLargeError(
                            f"Bale file exceeds maximum allowed size ({total} > {max_bytes})"
                        )
                    chunks.append(chunk)

        return b"".join(chunks)

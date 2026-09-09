from abc import ABC, abstractmethod
from typing import Any

import httpx
from django.conf import settings


class ExtractionProvider(ABC):
    key: str

    @abstractmethod
    def extract(self, *, schema: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        raise NotImplementedError


class HTTPExtractionProvider(ExtractionProvider):
    key = "http"

    def __init__(self, endpoint: str, api_key: str = "", timeout: float = 120.0) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout

    def extract(self, *, schema: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.endpoint:
            raise RuntimeError("AI_EXTRACTION_ENDPOINT is required")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = httpx.post(
            self.endpoint,
            headers=headers,
            json={"schema": schema, "evidence": evidence},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Extraction provider returned a non-object response")
        return data


def get_extraction_provider() -> ExtractionProvider:
    if settings.AI_EXTRACTION_PROVIDER == "http":
        return HTTPExtractionProvider(
            endpoint=settings.AI_EXTRACTION_ENDPOINT,
            api_key=settings.AI_EXTRACTION_API_KEY,
            timeout=settings.AI_EXTRACTION_TIMEOUT_SECONDS,
        )
    raise RuntimeError(f"Unsupported extraction provider: {settings.AI_EXTRACTION_PROVIDER}")

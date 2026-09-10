from abc import ABC, abstractmethod
import json
import logging
from typing import Any

import httpx
from django.conf import settings

from apps.system.integrations import get_avalai_config

logger = logging.getLogger(__name__)


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
        data.setdefault("facts", [])
        data.setdefault("conflicts", [])
        data.setdefault("decision_gaps", [])
        return data


class AvalAIExtractionProvider(ExtractionProvider):
    key = "avalai"

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 120.0) -> None:
        if not api_key:
            raise RuntimeError("AvalAI API Key is required")
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def extract(self, *, schema: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        instruction = (
            "You are the evidence-grounded intake and professional decision-gap detector for a case-management system. "
            "The schema may include professional_playbook. Treat that playbook as binding context: adopt its role, objectives, "
            "analysis_dimensions, decision_gap_rules and specialty when deciding what matters and what requires human judgment. "
            "Return ONLY one JSON object with keys facts, conflicts, and decision_gaps. facts must contain field, value, optional "
            "normalized_value, confidence (0..1), and evidence_ids. conflicts must identify a schema field only when genuinely "
            "different evidence supports incompatible values. decision_gaps are NOT missing-field questions. Create one only when "
            "the available evidence is already read but a material conclusion under the active professional playbook still requires "
            "human specialist judgment. Each decision gap must contain field, rationale, prompt, evidence_ids, and importance "
            "(high|medium). Never repeat a factual question answerable from evidence. Before declaring a fact missing, search all "
            "document pages, image analyses, transcript segments, and messages. Clearly distinguish fact from inference and expert "
            "opinion. Do not invent facts, sources, legal conclusions, coverage conclusions, technical causes, or professional opinions."
        )
        user_payload = json.dumps(
            {"schema": schema, "evidence": evidence},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": user_payload},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        trace = response.headers.get("avalai-request-id", "")
        if trace:
            logger.info("AvalAI extraction completed avalai-request-id=%s", trace)
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("AvalAI returned an invalid extraction response") from exc
        if not isinstance(result, dict):
            raise RuntimeError("AvalAI extraction response is not a JSON object")
        result.setdefault("facts", [])
        result.setdefault("conflicts", [])
        result.setdefault("decision_gaps", [])
        result["model"] = str(payload.get("model") or self.model)
        return result


def get_extraction_provider() -> ExtractionProvider:
    avalai = get_avalai_config()
    if avalai.enabled:
        return AvalAIExtractionProvider(
            base_url=avalai.base_url,
            api_key=avalai.api_key,
            model=avalai.text_model,
            timeout=avalai.timeout_seconds,
        )

    if settings.AI_EXTRACTION_PROVIDER == "http":
        return HTTPExtractionProvider(
            endpoint=settings.AI_EXTRACTION_ENDPOINT,
            api_key=settings.AI_EXTRACTION_API_KEY,
            timeout=settings.AI_EXTRACTION_TIMEOUT_SECONDS,
        )
    raise RuntimeError(f"Unsupported extraction provider: {settings.AI_EXTRACTION_PROVIDER}")

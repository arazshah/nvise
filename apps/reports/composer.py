from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from apps.intelligence.playbooks import resolve_playbook, serialize_playbook
from apps.system.integrations import get_avalai_config

logger = logging.getLogger(__name__)


def _fallback_sections(*, playbook, facts: dict[str, Any], limitations: list[dict[str, Any]]) -> list[dict[str, str]]:
    fact_lines = [f"{item['label']}: {item['value']}" for item in facts.values()]
    base = "\n".join(fact_lines) or "اطلاعات قابل اتکای کافی برای این بخش در پرونده ثبت نشده است."
    sections = []
    for index, title in enumerate(playbook.report_sections):
        key = f"section_{index + 1}"
        if "محدودیت" in title:
            if limitations:
                detail = "\n".join(
                    f"- {item['field_label']}: {item['issue_type_label']}؛ {item['resolution_label']}"
                    + (f"؛ {item['resolution_note']}" if item.get("resolution_note") else "")
                    for item in limitations
                )
                content = "محدودیت‌ها و موارد نامشخص این نسخه:\n" + detail
            else:
                content = "در زمان تهیه این نسخه، محدودیت یا مورد نامشخص ثبت‌شده‌ای باقی نمانده است."
        else:
            content = base
        sections.append({"key": key, "title": title, "content": content})
    return sections


def fallback_report(*, case, facts: dict[str, Any], limitations: list[dict[str, Any]]) -> dict[str, Any]:
    playbook = resolve_playbook(case)
    summary = "پیش‌نویس گزارش بر پایه اطلاعات استخراج‌شده و شواهد قابل ردیابی پرونده تهیه شده است."
    if limitations:
        summary += f" این نسخه با {len(limitations)} مورد اطلاعات نامشخص یا محدودیت ثبت‌شده تهیه شده است."
    return {
        "title": f"{playbook.title} - {case.title or case.case_code}",
        "summary": summary,
        "sections": _fallback_sections(playbook=playbook, facts=facts, limitations=limitations),
        "composer": "fallback",
    }


def compose_professional_report(*, case, facts: dict[str, Any], limitations: list[dict[str, Any]]) -> dict[str, Any]:
    config = get_avalai_config()
    if not config.enabled or not config.api_key:
        return fallback_report(case=case, facts=facts, limitations=limitations)

    playbook = resolve_playbook(case)
    playbook_payload = serialize_playbook(case)
    allowed_sections = [
        {"key": f"section_{index + 1}", "title": title}
        for index, title in enumerate(playbook.report_sections)
    ]
    payload = {
        "case": {
            "case_code": case.case_code,
            "title": case.title,
            "vertical": case.vertical_key,
            "sub_vertical": case.sub_vertical_key,
            "case_type": getattr(case, "case_type_key", ""),
        },
        "playbook": playbook_payload,
        "facts": facts,
        "limitations": limitations,
        "allowed_sections": allowed_sections,
    }
    instruction = (
        "You are the professional report composer for Nvise. Write a Persian professional report for the specialist identified "
        "by the supplied playbook. Return ONLY a JSON object with title, summary, and sections. sections must use exactly the "
        "provided allowed section keys and titles, in the same order. Use only supplied facts and limitations. Do not invent "
        "dates, amounts, policy terms, legal rules, technical specifications, causes, coverages, exclusions, or conclusions. "
        "Distinguish direct facts from interpretations. When evidence is insufficient, use cautious language such as 'بر اساس "
        "مدارک موجود' or explicitly state that a definitive conclusion is not possible. Never present an unsupported legal, "
        "coverage, liability, root-cause, or financial conclusion as certain. The report must be coherent narrative prose, not "
        "a label:value dump. Preserve every material limitation and mention the limitation count in the summary when limitations "
        "exist. Each section object must contain key, title, content."
    )
    try:
        response = httpx.post(
            f"{config.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
            json={
                "model": config.text_model,
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=config.timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json()
        content = raw["choices"][0]["message"]["content"]
        result = json.loads(content)
        sections = result.get("sections")
        if not isinstance(sections, list) or len(sections) != len(allowed_sections):
            raise ValueError("Invalid report section count")
        normalized = []
        for expected, section in zip(allowed_sections, sections):
            if not isinstance(section, dict) or section.get("key") != expected["key"]:
                raise ValueError("Invalid report section key")
            text = str(section.get("content") or "").strip()
            normalized.append({"key": expected["key"], "title": expected["title"], "content": text})
        summary = str(result.get("summary") or "").strip()
        if limitations and f"{len(limitations)}" not in summary:
            summary += f" این نسخه با {len(limitations)} مورد اطلاعات نامشخص یا محدودیت ثبت‌شده تهیه شده است."
        return {
            "title": str(result.get("title") or f"{playbook.title} - {case.title or case.case_code}").strip(),
            "summary": summary,
            "sections": normalized,
            "composer": "avalai",
            "model": str(raw.get("model") or config.text_model),
        }
    except Exception:
        logger.exception("Professional report composition failed; using safe fallback", extra={"case_id": str(case.id)})
        return fallback_report(case=case, facts=facts, limitations=limitations)

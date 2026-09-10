from __future__ import annotations

import hashlib
import json

import httpx
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.system.integrations import get_avalai_config

from .actions import create_manual_action
from .models import Case, CaseActionSuggestion, CaseEvent


def _evidence_payload(case: Case, limit: int = 60) -> list[dict]:
    rows = []
    for item in case.evidence_items.order_by("-created_at")[:limit]:
        text = (item.text or "").strip()
        if not text:
            continue
        rows.append(
            {
                "evidence_id": str(item.id),
                "source_kind": item.source_kind,
                "text": text[:2500],
                "metadata": {
                    "filename": (item.metadata or {}).get("filename"),
                    "page": (item.metadata or {}).get("page"),
                },
            }
        )
    return rows


def _fingerprint(title: str, rationale: str) -> str:
    normalized = " ".join(f"{title} {rationale}".lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_due(value):
    if not value or not isinstance(value, str):
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def generate_action_suggestions(case: Case) -> list[CaseActionSuggestion]:
    if case.lifecycle_status != Case.LifecycleStatus.ACTIVE:
        return []
    evidence = _evidence_payload(case)
    if not evidence:
        return []

    config = get_avalai_config()
    if not config.enabled or not config.api_key:
        return []

    instruction = (
        "You suggest concrete next professional actions for a case-management system. "
        "Return ONLY JSON with key suggestions. Each suggestion must have title_fa, description_fa, "
        "rationale_fa, evidence_ids, confidence (0..1), and due_at. Suggest only an action that is "
        "supported by the supplied evidence: an explicit commitment, missing document to obtain, "
        "follow-up to perform, scheduled visit/meeting, review to complete, or clear next professional step. "
        "Do not invent facts, people, dates, deadlines, legal conclusions, insurance coverage conclusions, "
        "or technical causes. due_at must be null unless an explicit date/time in evidence supports it. "
        "Write all user-facing text in Persian. Maximum 5 suggestions."
    )
    response = httpx.post(
        f"{config.base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": config.text_model,
            "messages": [
                {"role": "system", "content": instruction},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "case": {
                                "title": case.title,
                                "case_type": case.case_type_key,
                                "profession": case.created_by.profession_key,
                                "specialty": case.created_by.specialty_key,
                            },
                            "evidence": evidence,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=config.timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        result = json.loads(payload["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("پاسخ پیشنهاد اقدام معتبر نبود.") from exc

    valid_evidence = {row["evidence_id"] for row in evidence}
    created = []
    for raw in (result.get("suggestions") or [])[:5]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title_fa") or "").strip()
        rationale = str(raw.get("rationale_fa") or "").strip()
        if not title or not rationale:
            continue
        evidence_ids = [
            str(item)
            for item in (raw.get("evidence_ids") or [])
            if str(item) in valid_evidence
        ]
        if not evidence_ids:
            continue
        try:
            confidence = float(raw.get("confidence"))
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))
        fingerprint = _fingerprint(title, rationale)
        suggestion, was_created = CaseActionSuggestion.objects.get_or_create(
            case=case,
            fingerprint=fingerprint,
            defaults={
                "title": title[:255],
                "description": str(raw.get("description_fa") or "").strip(),
                "rationale": rationale,
                "suggested_due_at": _parse_due(raw.get("due_at")),
                "source_evidence_ids": evidence_ids,
                "confidence": confidence,
                "provider": "avalai",
                "model_name": str(payload.get("model") or config.text_model)[:128],
            },
        )
        if was_created:
            created.append(suggestion)
    return created


@transaction.atomic
def accept_action_suggestion(*, suggestion: CaseActionSuggestion, user):
    locked = CaseActionSuggestion.objects.select_for_update().select_related("case").get(pk=suggestion.pk)
    if locked.status != CaseActionSuggestion.Status.PROPOSED:
        return locked.accepted_action
    action = create_manual_action(
        case=locked.case,
        user=user,
        title=locked.title,
        description=locked.description or locked.rationale,
        due_at=locked.suggested_due_at,
    )
    action.source_event = "ai.suggestion"
    action.metadata = {
        **(action.metadata or {}),
        "suggestion_id": str(locked.id),
        "source_evidence_ids": list(locked.source_evidence_ids or []),
        "suggestion_confidence": locked.confidence,
    }
    action.save(update_fields=["source_event", "metadata", "updated_at"])
    locked.status = CaseActionSuggestion.Status.ACCEPTED
    locked.accepted_action = action
    locked.reviewed_by = user
    locked.reviewed_at = timezone.now()
    locked.save(update_fields=["status", "accepted_action", "reviewed_by", "reviewed_at"])
    CaseEvent.objects.create(
        case=locked.case,
        event_type="case.action_suggestion_accepted",
        actor=user,
        payload={"suggestion_id": str(locked.id), "action_id": str(action.id)},
    )
    return action


@transaction.atomic
def reject_action_suggestion(*, suggestion: CaseActionSuggestion, user) -> None:
    locked = CaseActionSuggestion.objects.select_for_update().get(pk=suggestion.pk)
    if locked.status != CaseActionSuggestion.Status.PROPOSED:
        return
    locked.status = CaseActionSuggestion.Status.REJECTED
    locked.reviewed_by = user
    locked.reviewed_at = timezone.now()
    locked.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    CaseEvent.objects.create(
        case=locked.case,
        event_type="case.action_suggestion_rejected",
        actor=user,
        payload={"suggestion_id": str(locked.id)},
    )

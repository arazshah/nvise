from __future__ import annotations

from typing import Any

from apps.cases.models import Case

from .models import ExtractedFact


def _display_value(fact: ExtractedFact) -> Any:
    return fact.normalized_value if fact.normalized_value is not None else fact.value


def _source_label(evidence) -> str:
    metadata = evidence.metadata or {}
    if evidence.source_kind == "document_page":
        filename = metadata.get("filename") or "سند"
        page = metadata.get("page")
        return f"{filename}، صفحه {page}" if page else str(filename)
    if evidence.source_kind == "image_analysis":
        return str(metadata.get("filename") or "تصویر پرونده")
    if evidence.source_kind == "transcript_segment":
        start_ms = evidence.start_ms or 0
        seconds = start_ms // 1000
        minute, second = divmod(seconds, 60)
        return f"فایل صوتی، {minute:02d}:{second:02d}"
    if evidence.source_kind == "message":
        return "پیام کاربر"
    return "مدرک پرونده"


def latest_fact_ledger(case: Case) -> list[dict[str, Any]]:
    """Return the latest extraction as a source-aware professional fact ledger."""
    latest_run = case.extraction_runs.filter(status="completed").order_by(
        "-completed_at", "-created_at"
    ).first()
    if latest_run is None:
        return []

    facts = (
        ExtractedFact.objects.filter(extraction_run=latest_run)
        .exclude(status=ExtractedFact.Status.REJECTED)
        .select_related("field")
        .prefetch_related("evidence_links__evidence")
        .order_by("field__sequence", "created_at")
    )

    ledger: list[dict[str, Any]] = []
    for fact in facts:
        sources = []
        seen = set()
        for link in fact.evidence_links.all():
            evidence = link.evidence
            label = _source_label(evidence)
            if label in seen:
                continue
            seen.add(label)
            sources.append(
                {
                    "evidence_id": str(evidence.id),
                    "source_kind": evidence.source_kind,
                    "label": label,
                    "start_ms": evidence.start_ms,
                    "end_ms": evidence.end_ms,
                    "metadata": evidence.metadata or {},
                }
            )

        ledger.append(
            {
                "fact_id": str(fact.id),
                "field_key": fact.field.key,
                "label": fact.field.label,
                "value": _display_value(fact),
                "confidence": fact.confidence,
                "status": fact.status,
                "sources": sources,
                "source_count": len(sources),
            }
        )
    return ledger


def ledger_quality_summary(case: Case) -> dict[str, int]:
    ledger = latest_fact_ledger(case)
    sourced = sum(1 for row in ledger if row["source_count"] > 0)
    high_confidence = sum(
        1 for row in ledger if row["confidence"] is not None and row["confidence"] >= 0.8
    )
    conflicted = sum(1 for row in ledger if row["status"] == ExtractedFact.Status.CONFLICTED)
    return {
        "total": len(ledger),
        "sourced": sourced,
        "high_confidence": high_confidence,
        "conflicted": conflicted,
    }

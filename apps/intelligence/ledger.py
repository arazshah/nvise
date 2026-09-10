from __future__ import annotations

from typing import Any

from apps.cases.models import Case

from .models import ExtractedFact


def confidence_band(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 0.85:
        return "high"
    if value >= 0.60:
        return "medium"
    return "low"


def _source_label(evidence) -> str:
    metadata = evidence.metadata or {}
    filename = metadata.get("filename")
    page = metadata.get("page")
    if filename and page:
        return f"{filename} · صفحه {page}"
    if filename:
        return str(filename)
    if evidence.source_kind == "transcript_segment":
        if evidence.start_ms is not None:
            seconds = evidence.start_ms // 1000
            return f"پیام صوتی · {seconds // 60:02d}:{seconds % 60:02d}"
        return "پیام صوتی"
    if evidence.source_kind == "image_analysis":
        return "تصویر پرونده"
    return "پیام پرونده"


def build_fact_ledger(case: Case) -> list[dict[str, Any]]:
    latest_run = case.extraction_runs.filter(status="completed").order_by("-completed_at", "-created_at").first()
    if latest_run is None:
        return []
    facts = (
        ExtractedFact.objects.filter(extraction_run=latest_run)
        .exclude(status=ExtractedFact.Status.REJECTED)
        .select_related("field")
        .prefetch_related("evidence_links__evidence")
        .order_by("field__sequence", "created_at")
    )
    ledger = []
    for fact in facts:
        sources = []
        for link in fact.evidence_links.all():
            evidence = link.evidence
            sources.append(
                {
                    "evidence_id": str(evidence.id),
                    "kind": evidence.source_kind,
                    "label": _source_label(evidence),
                    "page": (evidence.metadata or {}).get("page"),
                    "filename": (evidence.metadata or {}).get("filename"),
                    "start_ms": evidence.start_ms,
                    "end_ms": evidence.end_ms,
                    "relevance": link.relevance,
                }
            )
        ledger.append(
            {
                "fact_id": str(fact.id),
                "field_key": fact.field.key,
                "field_label": fact.field.label,
                "value": fact.normalized_value if fact.normalized_value is not None else fact.value,
                "confidence": fact.confidence,
                "confidence_band": confidence_band(fact.confidence),
                "status": fact.status,
                "source_count": len(sources),
                "sources": sources,
            }
        )
    return ledger

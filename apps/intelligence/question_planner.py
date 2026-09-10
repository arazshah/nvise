from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.evidence.models import Evidence

from .models import CaseFieldIssue, ExtractedFact


@dataclass(frozen=True)
class PlannedQuestion:
    category: str
    should_ask: bool
    title: str
    explanation: str
    prompt: str
    candidates: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "بله" if value else "خیر"
    return str(value).strip()


def _source_label(evidence: Evidence) -> str:
    metadata = evidence.metadata or {}
    filename = str(metadata.get("filename") or "").strip()
    page = metadata.get("page")
    if evidence.source_kind == Evidence.SourceKind.TRANSCRIPT_SEGMENT:
        seconds = int((evidence.start_ms or 0) / 1000)
        minute, second = divmod(seconds, 60)
        return f"فایل صوتی، {minute:02d}:{second:02d}"
    if filename:
        return f"{filename}، صفحه {page}" if page else filename
    if evidence.source_kind == Evidence.SourceKind.IMAGE_ANALYSIS:
        return "تصویر پرونده"
    if evidence.source_kind == Evidence.SourceKind.DOCUMENT_PAGE:
        return f"سند پرونده، صفحه {page}" if page else "سند پرونده"
    return "اطلاعات ثبت‌شده در پرونده"


def _fact_sources(fact: ExtractedFact) -> tuple[str, ...]:
    labels: list[str] = []
    for link in fact.evidence_links.select_related("evidence").all():
        label = _source_label(link.evidence)
        if label not in labels:
            labels.append(label)
    return tuple(labels[:4])


def _latest_field_facts(issue: CaseFieldIssue) -> list[ExtractedFact]:
    latest_run = issue.case.extraction_runs.filter(status="completed").order_by(
        "-completed_at", "-created_at"
    ).first()
    if latest_run is None:
        return []
    return list(
        ExtractedFact.objects.filter(
            extraction_run=latest_run,
            field=issue.field,
        )
        .exclude(status=ExtractedFact.Status.REJECTED)
        .prefetch_related("evidence_links__evidence")
        .order_by("-confidence", "created_at")
    )


def _field_is_critical(issue: CaseFieldIssue) -> bool:
    hints = issue.field.extraction_hints or {}
    follow_up = str(hints.get("follow_up") or "").lower()
    if follow_up in {"never", "optional", "low"}:
        return False
    if follow_up in {"critical", "required", "always"}:
        return True
    return bool(issue.field.required)


def plan_question(issue: CaseFieldIssue) -> PlannedQuestion:
    facts = _latest_field_facts(issue)
    label = issue.field.label
    details = issue.details or {}

    # A missing issue with a usable fact is stale. Never ask the user for information
    # that the current evidence ledger already contains.
    usable = [fact for fact in facts if fact.status != ExtractedFact.Status.CONFLICTED]
    if issue.issue_type == CaseFieldIssue.IssueType.MISSING and usable:
        best = usable[0]
        value = _display_value(
            best.normalized_value if best.normalized_value is not None else best.value
        )
        return PlannedQuestion(
            category="skip",
            should_ask=False,
            title="اطلاعات در پرونده پیدا شد",
            explanation=f"«{label}» از شواهد پرونده استخراج شده است: {value}",
            prompt="",
            candidates=(value,) if value else (),
            sources=_fact_sources(best),
        )

    if issue.issue_type == CaseFieldIssue.IssueType.CONFLICT:
        values: list[str] = []
        sources: list[str] = []
        for fact in facts:
            value = _display_value(
                fact.normalized_value if fact.normalized_value is not None else fact.value
            )
            if value and value not in values:
                values.append(value)
            for source in _fact_sources(fact):
                if source not in sources:
                    sources.append(source)
        if not values:
            values = [str(value) for value in details.get("values", []) if str(value).strip()]
        rendered = "، ".join(values[:4]) or "چند مقدار متفاوت"
        return PlannedQuestion(
            category="conflict",
            should_ask=True,
            title="تعارض واقعی بین شواهد",
            explanation=f"برای «{label}» بیش از یک مقدار در پرونده پیدا شده است: {rendered}.",
            prompt=f"کدام مقدار باید مبنای تحلیل و گزارش «{label}» قرار گیرد؟",
            candidates=tuple(values[:4]),
            sources=tuple(sources[:4]),
        )

    if issue.issue_type == CaseFieldIssue.IssueType.INVALID:
        current = _display_value(details.get("value"))
        explanation = f"برای «{label}» یک مقدار پیدا شد، اما برای استفاده قطعی قابل اتکا نیست."
        if current:
            explanation += f" مقدار فعلی: {current}"
        return PlannedQuestion(
            category="confirm",
            should_ask=True,
            title="نیاز به تأیید",
            explanation=explanation,
            prompt=f"لطفاً مقدار صحیح «{label}» را تأیید یا اصلاح کنید.",
            candidates=(current,) if current else (),
        )

    if issue.issue_type == CaseFieldIssue.IssueType.MISSING:
        if not _field_is_critical(issue):
            return PlannedQuestion(
                category="skip",
                should_ask=False,
                title="اطلاعات غیرضروری",
                explanation=f"«{label}» در پرونده پیدا نشد، اما برای ادامه تحلیل فعلی ضروری نیست.",
                prompt="",
            )
        return PlannedQuestion(
            category="critical_missing",
            should_ask=True,
            title="اطلاعات ضروری پیدا نشد",
            explanation=(
                f"پس از بررسی متن‌ها، صوت‌ها و مدارک پردازش‌شده پرونده، «{label}» پیدا نشد. "
                "این مورد برای نتیجه یا گزارش فعلی اهمیت دارد."
            ),
            prompt=f"اگر این اطلاعات را در اختیار دارید، «{label}» را اعلام کنید یا مدرک مربوط را بفرستید.",
        )

    return PlannedQuestion(
        category="expert_judgment",
        should_ask=True,
        title="نیازمند نظر تخصصی",
        explanation="این موضوع از شواهد پرونده به‌تنهایی قابل تعیین قطعی نیست.",
        prompt=f"نظر تخصصی شما درباره «{label}» چیست؟",
    )

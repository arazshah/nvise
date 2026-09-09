from django.db import transaction

from apps.cases.models import Case, CaseEvent
from apps.cases.services import approve_case
from apps.intelligence.models import ExtractedFact

from .models import Report, ReportApproval, ReportRevision, ReportSection


SECTION_DEFINITIONS = [
    ("case_overview", "مشخصات پرونده"),
    ("incident", "شرح حادثه"),
    ("damage", "ارزیابی خسارت"),
    ("supporting_information", "اطلاعات تکمیلی"),
]


def _field_section(field_key: str) -> str:
    if field_key in {"policy_number", "insured_name", "property_type"}:
        return "case_overview"
    if field_key in {"incident_datetime", "incident_address", "incident_cause"}:
        return "incident"
    if field_key in {"damage_description", "estimated_damage_amount", "currency", "salvage_condition"}:
        return "damage"
    return "supporting_information"


def _latest_fact_map(case: Case) -> dict:
    latest_run = case.extraction_runs.filter(status="completed").order_by("-completed_at", "-created_at").first()
    if latest_run is None:
        return {}
    result = {}
    facts = (
        ExtractedFact.objects.filter(extraction_run=latest_run)
        .exclude(status=ExtractedFact.Status.REJECTED)
        .select_related("field")
        .prefetch_related("evidence_links__evidence")
        .order_by("field__sequence", "created_at")
    )
    for fact in facts:
        if fact.status == ExtractedFact.Status.CONFLICTED:
            continue
        result[fact.field.key] = {
            "label": fact.field.label,
            "value": fact.normalized_value if fact.normalized_value is not None else fact.value,
            "confidence": fact.confidence,
            "evidence": [
                {
                    "evidence_id": str(link.evidence_id),
                    "source_kind": link.evidence.source_kind,
                    "start_ms": link.evidence.start_ms,
                    "end_ms": link.evidence.end_ms,
                }
                for link in fact.evidence_links.all()
            ],
        }
    return result


@transaction.atomic
def generate_report_revision(*, case: Case, created_by=None) -> ReportRevision:
    if case.status != Case.Status.READY_FOR_REVIEW:
        raise ValueError("Report can only be generated for a case ready for review")
    facts = _latest_fact_map(case)
    report, _ = Report.objects.select_for_update().get_or_create(case=case)
    next_revision = (report.revisions.order_by("-revision_number").values_list("revision_number", flat=True).first() or 0) + 1
    revision = ReportRevision.objects.create(
        report=report,
        revision_number=next_revision,
        title=f"گزارش کارشناسی خسارت - {case.title or case.case_code}",
        summary="گزارش ساختاری بر پایه اطلاعات ثبت‌شده و شواهد قابل ردیابی پرونده.",
        structured_data={"case_code": case.case_code, "facts": facts},
        source_snapshot={
            "case_status": case.status,
            "vertical": case.vertical_key,
            "sub_vertical": case.sub_vertical_key,
            "open_issues": case.field_issues.filter(status="open").count(),
        },
        created_by=created_by,
    )
    grouped = {key: {} for key, _ in SECTION_DEFINITIONS}
    for field_key, payload in facts.items():
        grouped[_field_section(field_key)][field_key] = payload
    for sequence, (key, title) in enumerate(SECTION_DEFINITIONS):
        section_data = grouped[key]
        lines = [f"{item['label']}: {item['value']}" for item in section_data.values()]
        ReportSection.objects.create(
            revision=revision,
            key=key,
            title=title,
            sequence=sequence,
            content="\n".join(lines),
            data=section_data,
        )
    report.current_revision = revision
    report.status = Report.Status.READY_FOR_REVIEW
    report.save(update_fields=["current_revision", "status", "updated_at"])
    CaseEvent.objects.create(
        case=case,
        event_type="report.revision_created",
        actor=created_by,
        payload={"report_id": str(report.id), "revision": revision.revision_number},
    )
    return revision


@transaction.atomic
def approve_report(*, case: Case, user, note: str = "") -> Report:
    report = Report.objects.select_for_update().select_related("current_revision").get(case=case)
    if report.status != Report.Status.READY_FOR_REVIEW or report.current_revision_id is None:
        raise ValueError("Report is not ready for approval")
    ReportApproval.objects.create(
        report=report,
        revision=report.current_revision,
        approved_by=user,
        note=note,
    )
    report.status = Report.Status.APPROVED
    report.save(update_fields=["status", "updated_at"])
    approve_case(case=case, actor=user)
    return report

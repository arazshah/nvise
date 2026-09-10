from django.db import transaction

from apps.audit.services import record_audit_event
from apps.cases.models import Case, CaseEvent
from apps.intelligence.models import CaseFieldIssue, ExtractedFact
from apps.intelligence.playbooks import resolve_playbook

from .composer import compose_professional_report
from .models import Report, ReportApproval, ReportRevision, ReportSection


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
        evidence_rows = []
        for link in fact.evidence_links.all():
            item = link.evidence
            metadata = item.metadata or {}
            evidence_rows.append(
                {
                    "evidence_id": str(item.id),
                    "source_kind": item.source_kind,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "filename": metadata.get("filename"),
                    "page": metadata.get("page"),
                    "document_type": metadata.get("document_type"),
                }
            )
        result[fact.field.key] = {
            "label": fact.field.label,
            "value": fact.normalized_value if fact.normalized_value is not None else fact.value,
            "confidence": fact.confidence,
            "evidence": evidence_rows,
        }
    return result


def _issue_type_label(issue_type: str) -> str:
    return {
        CaseFieldIssue.IssueType.MISSING: "اطلاعات یافت نشد",
        CaseFieldIssue.IssueType.CONFLICT: "اطلاعات متناقض",
        CaseFieldIssue.IssueType.INVALID: "مقدار نامعتبر یا نامطمئن",
        CaseFieldIssue.IssueType.EXPERT_JUDGMENT: "نیازمند نظر تخصصی",
    }.get(issue_type, "مورد نیازمند بررسی")


def _issue_resolution_label(status: str) -> str:
    return {
        CaseFieldIssue.Status.UNAVAILABLE: "اطلاعات در دسترس نبود",
        CaseFieldIssue.Status.WAIVED: "با تصمیم کاربر، گزارش با اطلاعات فعلی ادامه یافت",
        CaseFieldIssue.Status.RESOLVED: "رفع شده",
    }.get(status, status)


def _report_limitations(case: Case) -> list[dict]:
    issues = (
        CaseFieldIssue.objects.filter(
            case=case,
            status__in=[CaseFieldIssue.Status.UNAVAILABLE, CaseFieldIssue.Status.WAIVED],
        )
        .select_related("field")
        .order_by("field__sequence", "created_at")
    )
    return [
        {
            "field_key": issue.field.key,
            "field_label": issue.field.label,
            "issue_type": issue.issue_type,
            "issue_type_label": _issue_type_label(issue.issue_type),
            "resolution_status": issue.status,
            "resolution_label": _issue_resolution_label(issue.status),
            "resolution_note": issue.resolution_note or "",
            "details": issue.details or {},
        }
        for issue in issues
    ]


def _limitation_section_data(limitations: list[dict]) -> dict:
    data = {}
    for index, item in enumerate(limitations, start=1):
        value_parts = [item["issue_type_label"], item["resolution_label"]]
        note = item.get("resolution_note", "").strip()
        if note:
            value_parts.append(note)
        data[f"limitation_{index}"] = {
            "label": item["field_label"],
            "value": " — ".join(value_parts),
            "field_key": item["field_key"],
            "issue_type": item["issue_type"],
            "resolution_status": item["resolution_status"],
        }
    return data


@transaction.atomic
def generate_report_revision(*, case: Case, created_by=None) -> ReportRevision:
    locked_case = Case.objects.select_for_update().select_related("created_by").get(pk=case.pk)
    if locked_case.lifecycle_status != Case.LifecycleStatus.ACTIVE:
        raise ValueError("Report can only be generated for an active case")
    if locked_case.analysis_status not in {Case.AnalysisStatus.COMPLETED, Case.AnalysisStatus.NEEDS_REVIEW}:
        raise ValueError("Case analysis must be completed before generating a report")
    if CaseFieldIssue.objects.filter(case=locked_case, status=CaseFieldIssue.Status.OPEN).exists():
        raise ValueError("Open analysis issues must be resolved or waived before generating a report")

    facts = _latest_fact_map(locked_case)
    limitations = _report_limitations(locked_case)
    playbook = resolve_playbook(locked_case)
    composed = compose_professional_report(case=locked_case, facts=facts, limitations=limitations)

    locked_case.status = Case.Status.READY_FOR_REVIEW
    locked_case.report_status = Case.ReportStatus.READY_FOR_REVIEW
    locked_case.save(update_fields=["status", "report_status", "updated_at"])

    report, _ = Report.objects.select_for_update().get_or_create(case=locked_case)
    next_revision = report.revisions.order_by("-revision_number").values_list("revision_number", flat=True).first() or 0
    next_revision += 1

    revision = ReportRevision.objects.create(
        report=report,
        revision_number=next_revision,
        title=composed["title"],
        summary=composed["summary"],
        structured_data={
            "case_code": locked_case.case_code,
            "facts": facts,
            "limitations": limitations,
            "has_limitations": bool(limitations),
            "playbook": playbook.key,
            "case_type": locked_case.case_type_key,
        },
        source_snapshot={
            "case_status": locked_case.status,
            "vertical": locked_case.vertical_key,
            "sub_vertical": locked_case.sub_vertical_key,
            "case_type": locked_case.case_type_key,
            "profession": locked_case.created_by.profession_key,
            "specialty": locked_case.created_by.specialty_key,
            "playbook": playbook.key,
            "composer": composed.get("composer", "fallback"),
            "composer_model": composed.get("model", ""),
            "open_issues": 0,
            "unavailable_issues": sum(1 for item in limitations if item["resolution_status"] == CaseFieldIssue.Status.UNAVAILABLE),
            "waived_issues": sum(1 for item in limitations if item["resolution_status"] == CaseFieldIssue.Status.WAIVED),
            "limitation_count": len(limitations),
        },
        created_by=created_by,
    )

    limitation_data = _limitation_section_data(limitations)
    for sequence, section in enumerate(composed["sections"]):
        ReportSection.objects.create(
            revision=revision,
            key=section["key"],
            title=section["title"],
            sequence=sequence,
            content=section["content"],
            data=limitation_data if section["key"] == "limitations" else {},
        )

    report.current_revision = revision
    report.status = Report.Status.READY_FOR_REVIEW
    report.save(update_fields=["current_revision", "status", "updated_at"])
    CaseEvent.objects.create(
        case=locked_case,
        event_type="report.revision_created",
        actor=created_by,
        payload={
            "report_id": str(report.id),
            "revision": revision.revision_number,
            "limitation_count": len(limitations),
            "playbook": playbook.key,
            "composer": composed.get("composer", "fallback"),
        },
    )
    record_audit_event(
        event_type="report.revision_created",
        actor=created_by,
        case=locked_case,
        object_type="report_revision",
        object_id=revision.id,
        metadata={
            "report_id": str(report.id),
            "revision": revision.revision_number,
            "limitation_count": len(limitations),
            "playbook": playbook.key,
            "composer": composed.get("composer", "fallback"),
            "composer_model": composed.get("model", ""),
        },
    )
    return revision


@transaction.atomic
def create_review_revision(*, case: Case, user, title: str, summary: str, section_contents: dict[str, str]) -> ReportRevision:
    if case.status != Case.Status.READY_FOR_REVIEW:
        raise ValueError("Only reports ready for review can be edited")
    report = Report.objects.select_for_update().get(case=case)
    current = ReportRevision.objects.prefetch_related("sections").get(pk=report.current_revision_id)
    next_revision = current.revision_number + 1
    revision = ReportRevision.objects.create(
        report=report,
        revision_number=next_revision,
        title=title.strip() or current.title,
        summary=summary.strip(),
        structured_data=current.structured_data,
        source_snapshot={
            **current.source_snapshot,
            "edited_from_revision": current.revision_number,
            "editor_user_id": str(user.pk),
        },
        created_by=user,
    )
    for section in current.sections.order_by("sequence", "key"):
        ReportSection.objects.create(
            revision=revision,
            key=section.key,
            title=section.title,
            sequence=section.sequence,
            content=section_contents.get(section.key, section.content).strip(),
            data=section.data,
        )
    report.current_revision = revision
    report.save(update_fields=["current_revision", "updated_at"])
    CaseEvent.objects.create(
        case=case,
        event_type="report.revision_edited",
        actor=user,
        payload={"report_id": str(report.id), "from_revision": current.revision_number, "to_revision": revision.revision_number},
    )
    record_audit_event(
        event_type="report.revision_edited",
        actor=user,
        case=case,
        object_type="report_revision",
        object_id=revision.id,
        metadata={"report_id": str(report.id), "from_revision": current.revision_number, "to_revision": revision.revision_number},
    )
    return revision


@transaction.atomic
def approve_report(*, case: Case, user, note: str = "") -> Report:
    report = Report.objects.select_for_update().get(case=case)
    if report.status != Report.Status.READY_FOR_REVIEW or report.current_revision_id is None:
        raise ValueError("Report is not ready for approval")
    revision = ReportRevision.objects.get(pk=report.current_revision_id)
    approval = ReportApproval.objects.create(report=report, revision=revision, approved_by=user, note=note)
    report.status = Report.Status.APPROVED
    report.save(update_fields=["status", "updated_at"])
    from apps.cases.services import approve_case
    approve_case(case=case, actor=user)
    record_audit_event(
        event_type="report.approved",
        actor=user,
        case=case,
        object_type="report_approval",
        object_id=approval.id,
        metadata={"report_id": str(report.id), "revision": revision.revision_number},
    )
    from apps.documents.services import ensure_docx_document
    ensure_docx_document(revision=revision, requested_by=user)
    return report

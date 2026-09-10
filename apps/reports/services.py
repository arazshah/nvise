from django.db import transaction

from apps.audit.services import record_audit_event
from apps.cases.models import Case, CaseEvent
from apps.evidence.models import Evidence
from apps.intelligence.models import CaseFieldIssue, ExtractedFact
from apps.intelligence.playbooks import resolve_playbook

from .composer import compose_professional_report
from .models import (
    ExpertFactDecision,
    Report,
    ReportApproval,
    ReportClaim,
    ReportClaimReview,
    ReportRevision,
    ReportSection,
    ReportSectionReview,
)


def _evidence_snapshot(item: Evidence) -> dict:
    metadata = item.metadata or {}
    return {
        "evidence_id": str(item.id),
        "source_kind": item.source_kind,
        "start_ms": item.start_ms,
        "end_ms": item.end_ms,
        "filename": metadata.get("filename"),
        "page": metadata.get("page"),
        "document_type": metadata.get("document_type"),
    }


def _latest_fact_map(case: Case) -> dict:
    latest_run = case.extraction_runs.filter(status="completed").order_by("-completed_at", "-created_at").first()
    if latest_run is None:
        return {}
    decisions = {
        item.field_id: item
        for item in ExpertFactDecision.objects.filter(
            case=case,
            source_fact__extraction_run=latest_run,
        ).select_related("source_fact", "reviewer")
    }
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
        decision = decisions.get(fact.field_id)
        if decision and decision.source_fact_id == fact.id and decision.decision == ExpertFactDecision.Decision.REJECTED:
            continue
        evidence_rows = [_evidence_snapshot(link.evidence) for link in fact.evidence_links.all()]
        value = fact.normalized_value if fact.normalized_value is not None else fact.value
        expert_decision = None
        if decision and decision.source_fact_id == fact.id:
            if decision.decision == ExpertFactDecision.Decision.CORRECTED:
                value = decision.corrected_value
            expert_decision = {
                "decision": decision.decision,
                "note": decision.note,
                "reviewer_id": str(decision.reviewer_id),
                "updated_at": decision.updated_at.isoformat(),
            }
        result[fact.field.key] = {
            "fact_id": str(fact.id),
            "field_id": str(fact.field_id),
            "label": fact.field.label,
            "value": value,
            "original_value": fact.normalized_value if fact.normalized_value is not None else fact.value,
            "confidence": fact.confidence,
            "evidence": evidence_rows,
            "expert_decision": expert_decision,
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


def _claim_evidence(fact_keys: list[str], facts: dict) -> list[dict]:
    seen = set()
    rows = []
    for key in fact_keys:
        for item in (facts.get(key) or {}).get("evidence") or []:
            evidence_id = item.get("evidence_id")
            if not evidence_id or evidence_id in seen:
                continue
            seen.add(evidence_id)
            rows.append(item)
    return rows


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
            "expert_fact_decision_count": sum(1 for item in facts.values() if item.get("expert_decision")),
        },
        created_by=created_by,
    )

    limitation_data = _limitation_section_data(limitations)
    for sequence, section_payload in enumerate(composed["sections"]):
        section = ReportSection.objects.create(
            revision=revision,
            key=section_payload["key"],
            title=section_payload["title"],
            sequence=sequence,
            content=section_payload["content"],
            data=limitation_data if section_payload["key"] == "limitations" else {},
        )
        for claim_sequence, claim in enumerate(section_payload.get("claims") or []):
            ReportClaim.objects.create(
                revision=revision,
                section=section,
                sequence=claim_sequence,
                claim_type=claim["claim_type"],
                text=claim["text"],
                fact_keys=claim.get("fact_keys") or [],
                evidence_snapshot=_claim_evidence(claim.get("fact_keys") or [], facts),
                confidence=claim.get("confidence"),
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
            "claim_count": revision.claims.count(),
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
            "claim_count": revision.claims.count(),
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
    current = ReportRevision.objects.prefetch_related("sections__claims").get(pk=report.current_revision_id)
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
        new_section = ReportSection.objects.create(
            revision=revision,
            key=section.key,
            title=section.title,
            sequence=section.sequence,
            content=section_contents.get(section.key, section.content).strip(),
            data=section.data,
        )
        for claim in section.claims.order_by("sequence", "id"):
            ReportClaim.objects.create(
                revision=revision,
                section=new_section,
                sequence=claim.sequence,
                claim_type=claim.claim_type,
                text=claim.text,
                fact_keys=claim.fact_keys,
                evidence_snapshot=claim.evidence_snapshot,
                confidence=claim.confidence,
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
def save_expert_fact_decision(*, case: Case, user, fact_id, decision: str, corrected_value=None, note: str = "") -> ExpertFactDecision:
    if decision not in ExpertFactDecision.Decision.values:
        raise ValueError("Invalid fact decision")
    fact = (
        ExtractedFact.objects.select_related("field", "extraction_run")
        .prefetch_related("evidence_links__evidence")
        .get(pk=fact_id, case=case)
    )
    latest_run = case.extraction_runs.filter(status="completed").order_by("-completed_at", "-created_at").first()
    if latest_run is None or fact.extraction_run_id != latest_run.id:
        raise ValueError("Only facts from the latest completed analysis can be reviewed")
    if decision == ExpertFactDecision.Decision.CORRECTED:
        if corrected_value is None or (isinstance(corrected_value, str) and not corrected_value.strip()):
            raise ValueError("Corrected value is required")
        if isinstance(corrected_value, str):
            corrected_value = corrected_value.strip()
    else:
        corrected_value = None
    evidence_snapshot = [_evidence_snapshot(link.evidence) for link in fact.evidence_links.all()]
    row, _ = ExpertFactDecision.objects.update_or_create(
        case=case,
        field=fact.field,
        defaults={
            "source_fact": fact,
            "reviewer": user,
            "decision": decision,
            "corrected_value": corrected_value,
            "note": note.strip(),
            "evidence_snapshot": evidence_snapshot,
        },
    )
    report = Report.objects.filter(case=case).first()
    if report and report.current_revision_id:
        report.status = Report.Status.DRAFT
        report.save(update_fields=["status", "updated_at"])
        case.report_status = Case.ReportStatus.DRAFT
        case.save(update_fields=["report_status", "updated_at"])
    CaseEvent.objects.create(
        case=case,
        event_type="case.fact_reviewed",
        actor=user,
        payload={
            "field_key": fact.field.key,
            "fact_id": str(fact.id),
            "decision": decision,
            "report_marked_stale": bool(report and report.current_revision_id),
        },
    )
    record_audit_event(
        event_type="case.fact_reviewed",
        actor=user,
        case=case,
        object_type="expert_fact_decision",
        object_id=row.id,
        metadata={
            "field_key": fact.field.key,
            "fact_id": str(fact.id),
            "decision": decision,
            "corrected_value": corrected_value,
            "evidence_ids": [item["evidence_id"] for item in evidence_snapshot],
        },
    )
    return row


@transaction.atomic
def save_claim_review(*, case: Case, user, claim_id, decision: str, note: str = "") -> ReportClaimReview:
    report = Report.objects.select_for_update().get(case=case)
    if report.status != Report.Status.READY_FOR_REVIEW or report.current_revision_id is None:
        raise ValueError("Report is not ready for claim review")
    if decision not in ReportClaimReview.Decision.values:
        raise ValueError("Invalid claim review decision")
    claim = ReportClaim.objects.select_related("revision", "section").get(
        pk=claim_id,
        revision_id=report.current_revision_id,
    )
    review, _ = ReportClaimReview.objects.update_or_create(
        claim=claim,
        reviewer=user,
        defaults={"decision": decision, "note": note.strip()},
    )
    CaseEvent.objects.create(
        case=case,
        event_type="report.claim_reviewed",
        actor=user,
        payload={
            "revision": claim.revision.revision_number,
            "claim_id": str(claim.id),
            "claim_type": claim.claim_type,
            "decision": decision,
        },
    )
    record_audit_event(
        event_type="report.claim_reviewed",
        actor=user,
        case=case,
        object_type="report_claim_review",
        object_id=review.id,
        metadata={
            "revision": claim.revision.revision_number,
            "claim_id": str(claim.id),
            "claim_type": claim.claim_type,
            "decision": decision,
            "fact_keys": claim.fact_keys,
            "evidence_ids": [item.get("evidence_id") for item in claim.evidence_snapshot if item.get("evidence_id")],
        },
    )
    return review


@transaction.atomic
def save_section_review(*, case: Case, user, section_id, decision: str, note: str = "", evidence_ids=None) -> ReportSectionReview:
    report = Report.objects.select_for_update().get(case=case)
    if report.status != Report.Status.READY_FOR_REVIEW or report.current_revision_id is None:
        raise ValueError("Report is not ready for expert review")
    if decision not in ReportSectionReview.Decision.values:
        raise ValueError("Invalid review decision")

    section = ReportSection.objects.select_related("revision").get(
        pk=section_id,
        revision_id=report.current_revision_id,
    )
    requested_ids = [str(item) for item in (evidence_ids or []) if item]
    evidence_rows = list(
        Evidence.objects.filter(case=case, id__in=requested_ids)
        .order_by("created_at")
        .values("id", "source_kind", "start_ms", "end_ms", "metadata")
    )
    evidence_snapshot = [
        {
            "evidence_id": str(item["id"]),
            "source_kind": item["source_kind"],
            "start_ms": item["start_ms"],
            "end_ms": item["end_ms"],
            "filename": (item["metadata"] or {}).get("filename"),
            "page": (item["metadata"] or {}).get("page"),
        }
        for item in evidence_rows
    ]
    review, _ = ReportSectionReview.objects.update_or_create(
        revision=section.revision,
        section=section,
        reviewer=user,
        defaults={
            "decision": decision,
            "note": note.strip(),
            "evidence_snapshot": evidence_snapshot,
        },
    )
    CaseEvent.objects.create(
        case=case,
        event_type="report.section_reviewed",
        actor=user,
        payload={
            "revision": section.revision.revision_number,
            "section_key": section.key,
            "decision": decision,
            "evidence_count": len(evidence_snapshot),
        },
    )
    record_audit_event(
        event_type="report.section_reviewed",
        actor=user,
        case=case,
        object_type="report_section_review",
        object_id=review.id,
        metadata={
            "revision": section.revision.revision_number,
            "section_key": section.key,
            "decision": decision,
            "evidence_ids": [item["evidence_id"] for item in evidence_snapshot],
        },
    )
    return review


def review_progress(*, revision: ReportRevision, user) -> dict:
    total = revision.sections.count()
    reviews = revision.section_reviews.filter(reviewer=user)
    accepted = reviews.filter(decision=ReportSectionReview.Decision.ACCEPTED).count()
    needs_edit = reviews.filter(decision=ReportSectionReview.Decision.NEEDS_EDIT).count()
    rejected = reviews.filter(decision=ReportSectionReview.Decision.REJECTED).count()
    reviewed = reviews.count()

    claim_total = revision.claims.count()
    claim_reviews = ReportClaimReview.objects.filter(claim__revision=revision, reviewer=user)
    claim_accepted = claim_reviews.filter(decision=ReportClaimReview.Decision.ACCEPTED).count()
    claim_needs_edit = claim_reviews.filter(decision=ReportClaimReview.Decision.NEEDS_EDIT).count()
    claim_rejected = claim_reviews.filter(decision=ReportClaimReview.Decision.REJECTED).count()
    claim_reviewed = claim_reviews.count()
    sections_ready = total > 0 and accepted == total
    claims_ready = claim_total == 0 or claim_accepted == claim_total
    return {
        "total": total,
        "reviewed": reviewed,
        "accepted": accepted,
        "needs_edit": needs_edit,
        "rejected": rejected,
        "remaining": max(total - reviewed, 0),
        "claim_total": claim_total,
        "claim_reviewed": claim_reviewed,
        "claim_accepted": claim_accepted,
        "claim_needs_edit": claim_needs_edit,
        "claim_rejected": claim_rejected,
        "claim_remaining": max(claim_total - claim_reviewed, 0),
        "can_approve": sections_ready and claims_ready,
    }


@transaction.atomic
def approve_report(*, case: Case, user, note: str = "") -> Report:
    report = Report.objects.select_for_update().get(case=case)
    if report.status != Report.Status.READY_FOR_REVIEW or report.current_revision_id is None:
        raise ValueError("Report is not ready for approval")
    revision = ReportRevision.objects.get(pk=report.current_revision_id)
    progress = review_progress(revision=revision, user=user)
    if not progress["can_approve"]:
        raise ValueError("All report sections and material claims must be explicitly accepted by the approving expert")
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

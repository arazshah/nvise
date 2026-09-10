import pytest

from apps.accounts.models import User
from apps.cases.models import Case
from apps.cases.services import create_case
from apps.evidence.models import Evidence
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.models import ExtractedFact, ExtractionRun, FactEvidence
from apps.messaging.models import CaseMessage
from apps.reports.models import ExpertFactDecision, Report, ReportClaimReview, ReportSectionReview
from apps.reports.services import (
    approve_report,
    generate_report_revision,
    review_progress,
    save_claim_review,
    save_expert_fact_decision,
    save_section_review,
)
from apps.tenants.models import Tenant, TenantMembership


def _grounded_case():
    user = User.objects.create_user(username="grounding-expert")
    tenant = Tenant.objects.create(name="Grounding", slug="grounding-expert")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="خسارت کارخانه")
    case.analysis_status = Case.AnalysisStatus.COMPLETED
    case.save(update_fields=["analysis_status", "updated_at"])
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(case=case, schema=schema, provider="test", status=ExtractionRun.Status.COMPLETED)
    message = CaseMessage.objects.create(
        user=user,
        case=case,
        assignment_status=CaseMessage.AssignmentStatus.ASSIGNED,
        provider="bale",
        external_chat_id="grounding-chat",
        external_message_id="grounding-message",
        message_type=CaseMessage.MessageType.TEXT,
        text="شماره بیمه‌نامه ۱۴۰۳/۱۰۰ است.",
    )
    evidence = Evidence.objects.create(
        case=case,
        source_kind=Evidence.SourceKind.MESSAGE,
        message=message,
        text=message.text,
    )
    fact = ExtractedFact.objects.create(
        case=case,
        field=schema.fields.get(key="policy_number"),
        extraction_run=run,
        value="۱۴۰۳/۱۰۰",
        normalized_value="۱۴۰۳/۱۰۰",
        confidence=0.96,
    )
    FactEvidence.objects.create(fact=fact, evidence=evidence, relevance=1.0)
    return user, case, fact, evidence


@pytest.mark.django_db
def test_claims_are_grounded_in_backend_evidence_and_fact_correction_regenerates_report():
    user, case, fact, evidence = _grounded_case()
    first = generate_report_revision(case=case, created_by=user)

    claim = first.claims.get(claim_type="fact")
    assert claim.fact_keys == ["policy_number"]
    assert claim.evidence_snapshot[0]["evidence_id"] == str(evidence.id)
    assert claim.text

    decision = save_expert_fact_decision(
        case=case,
        user=user,
        fact_id=fact.id,
        decision=ExpertFactDecision.Decision.CORRECTED,
        corrected_value="۱۴۰۳/۲۰۰",
        note="شماره بیمه‌نامه با اصل سند تطبیق و اصلاح شد.",
    )
    assert decision.corrected_value == "۱۴۰۳/۲۰۰"
    case.refresh_from_db()
    report = Report.objects.get(case=case)
    assert report.status == Report.Status.DRAFT
    assert case.report_status == Case.ReportStatus.DRAFT

    second = generate_report_revision(case=case, created_by=user)
    assert second.revision_number == first.revision_number + 1
    assert second.structured_data["facts"]["policy_number"]["value"] == "۱۴۰۳/۲۰۰"
    assert second.structured_data["facts"]["policy_number"]["original_value"] == "۱۴۰۳/۱۰۰"
    assert second.structured_data["facts"]["policy_number"]["expert_decision"]["decision"] == "corrected"


@pytest.mark.django_db
def test_material_claims_must_be_accepted_before_final_approval():
    user, case, _, _ = _grounded_case()
    revision = generate_report_revision(case=case, created_by=user)

    for section in revision.sections.all():
        save_section_review(
            case=case,
            user=user,
            section_id=section.id,
            decision=ReportSectionReview.Decision.ACCEPTED,
        )

    progress = review_progress(revision=revision, user=user)
    assert progress["accepted"] == progress["total"]
    assert progress["claim_total"] > 0
    assert progress["can_approve"] is False
    with pytest.raises(ValueError):
        approve_report(case=case, user=user)

    for claim in revision.claims.all():
        save_claim_review(
            case=case,
            user=user,
            claim_id=claim.id,
            decision=ReportClaimReview.Decision.ACCEPTED,
        )

    progress = review_progress(revision=revision, user=user)
    assert progress["claim_accepted"] == progress["claim_total"]
    assert progress["can_approve"] is True
    approved = approve_report(case=case, user=user)
    assert approved.status == Report.Status.APPROVED

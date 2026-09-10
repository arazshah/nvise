import pytest

from apps.accounts.models import User
from apps.cases.models import Case
from apps.cases.services import create_case
from apps.evidence.models import Evidence
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.models import ExtractedFact, ExtractionRun, FactEvidence
from apps.messaging.models import CaseMessage
from apps.reports.models import ReportSectionReview
from apps.reports.services import generate_report_revision, review_progress, save_section_review
from apps.tenants.models import Tenant, TenantMembership


@pytest.mark.django_db
def test_section_review_snapshots_only_case_evidence_and_unlocks_progress(client):
    user = User.objects.create_user(username="expert-reviewer")
    tenant = Tenant.objects.create(name="Expert", slug="expert-review")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده کارشناسی")
    case.analysis_status = Case.AnalysisStatus.COMPLETED
    case.save(update_fields=["analysis_status", "updated_at"])

    message = CaseMessage.objects.create(
        user=user,
        case=case,
        assignment_status=CaseMessage.AssignmentStatus.ASSIGNED,
        provider="bale",
        external_chat_id="expert-chat",
        external_message_id="expert-message",
        message_type=CaseMessage.MessageType.TEXT,
        text="نام بیمه‌گذار آراز شاهکرمی است.",
    )
    evidence = Evidence.objects.create(
        case=case,
        source_kind=Evidence.SourceKind.MESSAGE,
        message=message,
        text=message.text,
    )
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(
        case=case,
        schema=schema,
        provider="test",
        status=ExtractionRun.Status.COMPLETED,
    )
    fact = ExtractedFact.objects.create(
        case=case,
        field=schema.fields.get(key="insured_name"),
        extraction_run=run,
        value="آراز شاهکرمی",
        normalized_value="آراز شاهکرمی",
        confidence=0.97,
    )
    FactEvidence.objects.create(fact=fact, evidence=evidence, relevance=1.0)

    revision = generate_report_revision(case=case, created_by=user)
    first_section = revision.sections.first()
    review = save_section_review(
        case=case,
        user=user,
        section_id=first_section.id,
        decision=ReportSectionReview.Decision.ACCEPTED,
        note="با منبع پرونده تطبیق داده شد.",
        evidence_ids=[evidence.id],
    )

    assert review.evidence_snapshot[0]["evidence_id"] == str(evidence.id)
    assert review.note == "با منبع پرونده تطبیق داده شد."
    progress = review_progress(revision=revision, user=user)
    assert progress["accepted"] == 1
    assert progress["remaining"] == revision.sections.count() - 1
    assert progress["can_approve"] is False

    client.force_login(user)
    response = client.get(f"/review/cases/{case.case_code}/review/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "داده‌های استخراج‌شده" in body
    assert "اطمینان 0.97" in body
    assert f"#evidence-{evidence.id}" in body
    assert "تصمیم برای هر بخش" in body
    assert "کنترل ادعاها و داده‌ها" in body


@pytest.mark.django_db
def test_review_rejects_section_from_old_revision():
    user = User.objects.create_user(username="revision-reviewer")
    tenant = Tenant.objects.create(name="Revision", slug="revision-review")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="نسخه‌ها")
    case.analysis_status = Case.AnalysisStatus.COMPLETED
    case.save(update_fields=["analysis_status", "updated_at"])

    first_revision = generate_report_revision(case=case, created_by=user)
    old_section = first_revision.sections.first()
    second_revision = generate_report_revision(case=case, created_by=user)
    assert second_revision.id != first_revision.id

    with pytest.raises(Exception):
        save_section_review(
            case=case,
            user=user,
            section_id=old_section.id,
            decision=ReportSectionReview.Decision.ACCEPTED,
        )

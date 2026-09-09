import pytest

from apps.accounts.models import User
from apps.cases.models import Case
from apps.cases.services import create_case
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.models import CaseFieldIssue, ExtractedFact, ExtractionRun
from apps.intelligence.results import analysis_result_summary, waive_open_issues
from apps.reports.services import generate_report_revision
from apps.tenants.models import Tenant, TenantMembership


@pytest.mark.django_db
def test_analysis_summary_counts_facts_and_open_issues():
    user = User.objects.create_user(username="analysis-summary")
    tenant = Tenant.objects.create(name="Personal", slug="analysis-summary")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده تحلیل")
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(
        case=case,
        schema=schema,
        provider="test",
        status=ExtractionRun.Status.COMPLETED,
    )
    insured = schema.fields.get(key="insured_name")
    address = schema.fields.get(key="incident_address")
    ExtractedFact.objects.create(
        case=case,
        field=insured,
        extraction_run=run,
        value="حسن آقا",
        status=ExtractedFact.Status.PROPOSED,
    )
    CaseFieldIssue.objects.create(
        case=case,
        field=address,
        issue_type=CaseFieldIssue.IssueType.MISSING,
    )

    summary = analysis_result_summary(case)

    assert summary["usable_facts"] == 1
    assert summary["open_issues"] == 1
    assert summary["missing"] == 1
    assert summary["has_issues"] is True


@pytest.mark.django_db
def test_report_requires_explicit_issue_resolution_or_waiver():
    user = User.objects.create_user(username="analysis-report-choice")
    tenant = Tenant.objects.create(name="Personal", slug="analysis-report-choice")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده گزارش")
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(
        case=case,
        schema=schema,
        provider="test",
        status=ExtractionRun.Status.COMPLETED,
    )
    field = schema.fields.get(key="insured_name")
    ExtractedFact.objects.create(
        case=case,
        field=field,
        extraction_run=run,
        value="حسن آقا",
    )
    missing_field = schema.fields.get(key="incident_address")
    CaseFieldIssue.objects.create(
        case=case,
        field=missing_field,
        issue_type=CaseFieldIssue.IssueType.MISSING,
    )
    case.analysis_status = Case.AnalysisStatus.NEEDS_REVIEW
    case.status = Case.Status.NEEDS_INFORMATION
    case.save(update_fields=["analysis_status", "status", "updated_at"])

    with pytest.raises(ValueError):
        generate_report_revision(case=case, created_by=user)

    assert waive_open_issues(case, actor=user) == 1
    case.refresh_from_db()
    revision = generate_report_revision(case=case, created_by=user)

    assert revision.revision_number == 1
    case.refresh_from_db()
    assert case.status == Case.Status.READY_FOR_REVIEW
    assert case.report_status == Case.ReportStatus.READY_FOR_REVIEW

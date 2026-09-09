import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.cases.models import Case
from apps.cases.services import create_case
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.models import CaseFieldIssue, ExtractionRun
from apps.reports.models import Report
from apps.tenants.models import Tenant, TenantMembership


@pytest.mark.django_db
def test_portal_can_waive_open_issue_and_generate_report(client):
    user = User.objects.create_user(username="portal-analysis-user")
    tenant = Tenant.objects.create(name="Personal", slug="portal-analysis")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده تست تحلیل")
    schema = ensure_fire_loss_schema()
    ExtractionRun.objects.create(
        case=case,
        schema=schema,
        provider="test",
        status=ExtractionRun.Status.COMPLETED,
    )
    field = schema.fields.get(key="incident_cause")
    issue = CaseFieldIssue.objects.create(
        case=case,
        field=field,
        issue_type=CaseFieldIssue.IssueType.MISSING,
    )
    case.analysis_status = Case.AnalysisStatus.NEEDS_REVIEW
    case.status = Case.Status.NEEDS_INFORMATION
    case.save(update_fields=["analysis_status", "status", "updated_at"])

    client.force_login(user)
    overview = client.get(reverse("portal:analysis-overview", args=[case.case_code]))
    assert overview.status_code == 200
    assert "موارد نیازمند بررسی" in overview.content.decode("utf-8")

    continued = client.post(reverse("portal:analysis-continue", args=[case.case_code]))
    assert continued.status_code == 302
    issue.refresh_from_db()
    case.refresh_from_db()
    assert issue.status == CaseFieldIssue.Status.WAIVED
    assert case.analysis_status == Case.AnalysisStatus.COMPLETED

    generated = client.post(reverse("portal:analysis-generate-report", args=[case.case_code]))
    assert generated.status_code == 302
    assert generated.url == reverse("portal:case-review", args=[case.case_code])
    assert Report.objects.filter(case=case, current_revision__isnull=False).exists()


@pytest.mark.django_db
def test_portal_analysis_is_tenant_scoped(client):
    owner = User.objects.create_user(username="portal-owner")
    outsider = User.objects.create_user(username="portal-outsider")
    tenant = Tenant.objects.create(name="Owner", slug="portal-owner-tenant")
    TenantMembership.objects.create(tenant=tenant, user=owner, role=TenantMembership.Role.OWNER)
    case = create_case(user=owner, tenant=tenant, title="پرونده خصوصی")

    client.force_login(outsider)
    response = client.get(reverse("portal:analysis-overview", args=[case.case_code]))
    assert response.status_code == 404

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.cases.models import Case
from apps.cases.services import create_case
from apps.tenants.models import Tenant, TenantMembership


@pytest.mark.django_db
def test_dashboard_only_shows_accessible_cases_and_counts_actions(client):
    user = User.objects.create_user(username="dashboard-user", display_name="کاربر آزمایشی")
    tenant = Tenant.objects.create(name="Personal", slug="dashboard-personal")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)

    other_user = User.objects.create_user(username="other-dashboard-user")
    other_tenant = Tenant.objects.create(name="Other", slug="dashboard-other")
    TenantMembership.objects.create(
        tenant=other_tenant,
        user=other_user,
        role=TenantMembership.Role.OWNER,
    )

    active_case = create_case(user=user, tenant=tenant, title="پرونده فعال")
    active_case.analysis_status = Case.AnalysisStatus.NEEDS_REVIEW
    active_case.save(update_fields=["analysis_status", "updated_at"])

    archived_case = create_case(user=user, tenant=tenant, title="پرونده بایگانی")
    archived_case.lifecycle_status = Case.LifecycleStatus.ARCHIVED
    archived_case.status = Case.Status.ARCHIVED
    archived_case.save(update_fields=["lifecycle_status", "status", "updated_at"])

    hidden_case = create_case(user=other_user, tenant=other_tenant, title="پرونده غیرمجاز")

    client.force_login(user)
    response = client.get(reverse("portal:dashboard"))

    assert response.status_code == 200
    assert response.context["total_count"] == 2
    assert response.context["active_count"] == 1
    assert response.context["archived_count"] == 1
    assert response.context["needs_action_count"] == 1
    content = response.content.decode("utf-8")
    assert active_case.title in content
    assert archived_case.title in content
    assert hidden_case.title not in content
    assert "نیازمند اقدام شما" in content

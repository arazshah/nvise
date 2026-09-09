import pytest

from apps.accounts.models import User
from apps.cases.services import create_case
from apps.subscriptions.models import UsageRecord
from apps.subscriptions.services import (
    QuotaExceededError,
    get_or_create_subscription,
    record_usage,
    subscription_snapshot,
)
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.services import MemberLimitExceededError, add_tenant_member


@pytest.mark.django_db
def test_case_quota_is_enforced_and_usage_is_metered():
    user = User.objects.create_user(username="quota-owner")
    tenant = Tenant.objects.create(name="Quota", slug="quota")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    subscription = get_or_create_subscription(tenant)
    subscription.plan.max_cases_per_period = 1
    subscription.plan.save(update_fields=["max_cases_per_period"])

    case = create_case(user=user, tenant=tenant, title="First")
    assert UsageRecord.objects.filter(tenant=tenant, metric=UsageRecord.Metric.CASE_CREATED).count() == 1

    with pytest.raises(QuotaExceededError):
        create_case(user=user, tenant=tenant, title="Second")

    snapshot = subscription_snapshot(tenant)
    assert snapshot["metrics"][UsageRecord.Metric.CASE_CREATED]["used"] == "1.000"
    assert case.tenant_id == tenant.id


@pytest.mark.django_db
def test_usage_recording_is_idempotent():
    tenant = Tenant.objects.create(name="Metered", slug="metered")
    get_or_create_subscription(tenant)
    first = record_usage(
        tenant=tenant,
        metric=UsageRecord.Metric.AI_EXTRACTION,
        quantity=1,
        idempotency_key="ai:test-run",
    )
    second = record_usage(
        tenant=tenant,
        metric=UsageRecord.Metric.AI_EXTRACTION,
        quantity=1,
        idempotency_key="ai:test-run",
    )
    assert first.id == second.id
    assert UsageRecord.objects.filter(idempotency_key="ai:test-run").count() == 1


@pytest.mark.django_db
def test_member_limit_is_enforced():
    owner = User.objects.create_user(username="owner-limit")
    colleague = User.objects.create_user(username="colleague-limit")
    tenant = Tenant.objects.create(name="Team", slug="team-limit")
    TenantMembership.objects.create(tenant=tenant, user=owner, role=TenantMembership.Role.OWNER)
    subscription = get_or_create_subscription(tenant)
    subscription.plan.max_members = 1
    subscription.plan.save(update_fields=["max_members"])

    with pytest.raises(MemberLimitExceededError):
        add_tenant_member(tenant=tenant, user=colleague)

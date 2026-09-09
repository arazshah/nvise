from datetime import timedelta

import pytest
from django.utils import timezone

from apps.subscriptions.models import Subscription, UsageRecord
from apps.subscriptions.services import (
    SubscriptionAccessError,
    assert_quota,
    get_or_create_subscription,
    refresh_subscription_state,
)
from apps.tenants.models import Tenant


@pytest.mark.django_db
def test_new_tenant_gets_one_time_30_day_trial():
    tenant = Tenant.objects.create(name="Trial account", slug="trial-account")

    subscription = get_or_create_subscription(tenant)

    assert subscription.plan.code == "trial"
    assert subscription.status == Subscription.Status.TRIALING
    assert subscription.plan.monthly_price == 0
    assert subscription.plan.max_cases_per_period == 5
    assert subscription.plan.max_stt_seconds_per_period == 1800
    assert subscription.plan.max_ai_extractions_per_period == 15
    assert subscription.plan.max_members == 1
    assert subscription.metadata["trial_granted"] is True
    assert timedelta(days=29, hours=23) < (
        subscription.current_period_end - subscription.current_period_start
    ) <= timedelta(days=30, minutes=1)

    same_subscription = get_or_create_subscription(tenant)
    assert same_subscription.pk == subscription.pk
    assert Subscription.objects.filter(tenant=tenant).count() == 1


@pytest.mark.django_db
def test_expired_trial_blocks_costly_operations_but_keeps_case_quota_available():
    tenant = Tenant.objects.create(name="Expired trial", slug="expired-trial")
    subscription = get_or_create_subscription(tenant)
    subscription.current_period_end = timezone.now() - timedelta(seconds=1)
    subscription.save(update_fields=["current_period_end", "updated_at"])

    refreshed = refresh_subscription_state(tenant)
    assert refreshed.status == Subscription.Status.EXPIRED

    with pytest.raises(SubscriptionAccessError) as exc_info:
        assert_quota(tenant, UsageRecord.Metric.STT_SECONDS, 1)
    assert exc_info.value.code == "trial_expired"

    with pytest.raises(SubscriptionAccessError) as exc_info:
        assert_quota(tenant, UsageRecord.Metric.AI_EXTRACTION, 1)
    assert exc_info.value.code == "trial_expired"

    # Repository/case management remains available after the trial, subject to
    # the trial plan's existing case-count ceiling.
    assert_quota(tenant, UsageRecord.Metric.CASE_CREATED, 1)

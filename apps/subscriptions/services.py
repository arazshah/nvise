from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.tenants.models import Tenant

from .models import Entitlement, Plan, Subscription, UsageRecord


class QuotaExceededError(PermissionError):
    def __init__(self, metric: str, limit: Decimal, used: Decimal) -> None:
        super().__init__(f"Quota exceeded for {metric}: used={used}, limit={limit}")
        self.metric = metric
        self.limit = limit
        self.used = used


PLAN_LIMIT_FIELDS = {
    UsageRecord.Metric.CASE_CREATED: "max_cases_per_period",
    UsageRecord.Metric.STT_SECONDS: "max_stt_seconds_per_period",
    UsageRecord.Metric.AI_EXTRACTION: "max_ai_extractions_per_period",
}


def ensure_default_plans() -> dict[str, Plan]:
    defaults = {
        "free": {
            "name": "Free",
            "monthly_price": 0,
            "currency": "IRR",
            "max_cases_per_period": 5,
            "max_stt_seconds_per_period": 1800,
            "max_ai_extractions_per_period": 25,
            "max_members": 1,
            "features": {"docx": True, "web_review": True},
        },
        "pro": {
            "name": "Pro",
            "monthly_price": 0,
            "currency": "IRR",
            "max_cases_per_period": 100,
            "max_stt_seconds_per_period": 36000,
            "max_ai_extractions_per_period": 500,
            "max_members": 5,
            "features": {"docx": True, "web_review": True, "priority_processing": True},
        },
    }
    result = {}
    for code, values in defaults.items():
        plan, _ = Plan.objects.get_or_create(code=code, defaults=values)
        result[code] = plan
    return result


@transaction.atomic
def get_or_create_subscription(tenant: Tenant) -> Subscription:
    locked_tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    subscription = Subscription.objects.select_for_update().filter(tenant=locked_tenant).first()
    if subscription is not None:
        return subscription
    free = ensure_default_plans()["free"]
    now = timezone.now()
    return Subscription.objects.create(
        tenant=locked_tenant,
        plan=free,
        status=Subscription.Status.ACTIVE,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )


@transaction.atomic
def change_plan(*, tenant: Tenant, plan: Plan) -> Subscription:
    subscription = get_or_create_subscription(tenant)
    subscription = Subscription.objects.select_for_update().get(pk=subscription.pk)
    subscription.plan = plan
    subscription.status = Subscription.Status.ACTIVE
    subscription.save(update_fields=["plan", "status", "updated_at"])
    return subscription


@transaction.atomic
def renew_subscription_period(*, tenant: Tenant, days: int = 30) -> Subscription:
    subscription = get_or_create_subscription(tenant)
    subscription = Subscription.objects.select_for_update().get(pk=subscription.pk)
    now = timezone.now()
    subscription.current_period_start = now
    subscription.current_period_end = now + timedelta(days=days)
    subscription.status = Subscription.Status.ACTIVE
    subscription.cancel_at_period_end = False
    subscription.save(
        update_fields=[
            "current_period_start",
            "current_period_end",
            "status",
            "cancel_at_period_end",
            "updated_at",
        ]
    )
    return subscription


@transaction.atomic
def set_subscription_status(*, tenant: Tenant, status: str) -> Subscription:
    if status not in Subscription.Status.values:
        raise ValueError("Invalid subscription status")
    subscription = get_or_create_subscription(tenant)
    subscription = Subscription.objects.select_for_update().get(pk=subscription.pk)
    subscription.status = status
    subscription.save(update_fields=["status", "updated_at"])
    return subscription


@transaction.atomic
def set_entitlement(*, tenant: Tenant, key: str, value, source=Entitlement.Source.OVERRIDE):
    subscription = get_or_create_subscription(tenant)
    entitlement, _ = Entitlement.objects.update_or_create(
        subscription=subscription,
        key=key,
        defaults={"value": value, "source": source},
    )
    return entitlement


def _active_subscription(tenant: Tenant) -> Subscription:
    subscription = get_or_create_subscription(tenant)
    now = timezone.now()
    if subscription.status not in {Subscription.Status.ACTIVE, Subscription.Status.TRIALING}:
        raise PermissionError("Tenant subscription is not active")
    if subscription.current_period_end <= now:
        raise PermissionError("Tenant subscription period has expired")
    return subscription


def entitlement_value(tenant: Tenant, key: str, default=None):
    subscription = _active_subscription(tenant)
    override = subscription.entitlements.filter(key=key).first()
    if override is not None:
        return override.value
    return subscription.plan.features.get(key, default)


def period_usage(tenant: Tenant, metric: str) -> Decimal:
    subscription = _active_subscription(tenant)
    value = (
        UsageRecord.objects.filter(
            tenant=tenant,
            metric=metric,
            occurred_at__gte=subscription.current_period_start,
            occurred_at__lt=subscription.current_period_end,
        ).aggregate(total=Sum("quantity"))["total"]
        or Decimal("0")
    )
    return Decimal(value)


def metric_limit(tenant: Tenant, metric: str) -> Decimal | None:
    subscription = _active_subscription(tenant)
    override = subscription.entitlements.filter(key=f"limit.{metric}").first()
    if override is not None:
        raw = override.value.get("value") if isinstance(override.value, dict) else override.value
        return Decimal(str(raw))
    field = PLAN_LIMIT_FIELDS.get(metric)
    if field is None:
        return None
    return Decimal(str(getattr(subscription.plan, field)))


def assert_quota(tenant: Tenant, metric: str, requested: Decimal | int | float = 1) -> None:
    requested = Decimal(str(requested))
    limit = metric_limit(tenant, metric)
    if limit is None:
        return
    used = period_usage(tenant, metric)
    if used + requested > limit:
        raise QuotaExceededError(metric=metric, limit=limit, used=used)


@transaction.atomic
def record_usage(
    *,
    tenant: Tenant,
    metric: str,
    quantity: Decimal | int | float,
    idempotency_key: str,
    case=None,
    metadata: dict | None = None,
) -> UsageRecord:
    record, _ = UsageRecord.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "tenant": tenant,
            "metric": metric,
            "quantity": Decimal(str(quantity)),
            "case": case,
            "metadata": metadata or {},
        },
    )
    return record


def subscription_snapshot(tenant: Tenant) -> dict:
    subscription = _active_subscription(tenant)
    metrics = {}
    for metric in PLAN_LIMIT_FIELDS:
        metrics[metric] = {
            "used": str(period_usage(tenant, metric)),
            "limit": str(metric_limit(tenant, metric)),
        }
    return {
        "status": subscription.status,
        "plan": subscription.plan.code,
        "period_start": subscription.current_period_start,
        "period_end": subscription.current_period_end,
        "metrics": metrics,
    }

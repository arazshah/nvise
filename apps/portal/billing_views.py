from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.subscriptions.models import Plan, UsageRecord
from apps.system.models import IntegrationSettings


STATUS_LABELS = {
    "trialing": "دوره آزمایشی",
    "active": "فعال",
    "past_due": "نیازمند پیگیری پرداخت",
    "cancelled": "لغو شده",
    "expired": "منقضی شده",
}


@login_required
@require_http_methods(["GET"])
def billing_overview(request):
    integration = IntegrationSettings.objects.filter(pk=1).first()
    membership = (
        request.user.tenant_memberships.select_related("tenant", "tenant__subscription__plan")
        .filter(is_active=True, tenant__is_active=True)
        .order_by("created_at")
        .first()
    )

    tenant = membership.tenant if membership else None
    subscription = getattr(tenant, "subscription", None) if tenant else None
    plan = subscription.plan if subscription else None

    if subscription:
        period_start = subscription.current_period_start
        period_end = subscription.current_period_end
    else:
        period_end = timezone.now()
        period_start = period_end - timedelta(days=30)

    usage = {}
    if tenant:
        usage = {
            row["metric"]: row["total"]
            for row in UsageRecord.objects.filter(
                tenant=tenant,
                occurred_at__gte=period_start,
                occurred_at__lt=period_end,
            )
            .values("metric")
            .annotate(total=Sum("quantity"))
        }

    billing_visible = integration.show_billing_portal if integration else True
    online_payment_enabled = integration.online_payment_enabled if integration else False
    provider_code = integration.payment_provider if integration else "bale"
    provider_label = "کیف پول بله" if provider_code == "bale" else provider_code
    payment_token_configured = bool(integration and integration.bale_payment_token)

    return render(
        request,
        "portal/billing.html",
        {
            "billing_visible": billing_visible,
            "tenant": tenant,
            "subscription": subscription,
            "subscription_status_label": (
                STATUS_LABELS.get(subscription.status, subscription.status) if subscription else "بدون اشتراک"
            ),
            "plan": plan,
            "plans": Plan.objects.filter(is_active=True).order_by("monthly_price", "name"),
            "usage_cases": usage.get(UsageRecord.Metric.CASE_CREATED, 0),
            "usage_stt": usage.get(UsageRecord.Metric.STT_SECONDS, 0),
            "usage_ai": usage.get(UsageRecord.Metric.AI_EXTRACTION, 0),
            "usage_docs": usage.get(UsageRecord.Metric.DOCUMENT_GENERATED, 0),
            "period_start": period_start,
            "period_end": period_end,
            "online_payment_enabled": online_payment_enabled,
            "payment_provider_label": provider_label,
            "payment_token_configured": payment_token_configured,
            "billing_notice": (
                integration.billing_notice
                if integration
                else "پرداخت اشتراک از طریق کیف پول بله انجام خواهد شد."
            ),
            "support_email": integration.support_email if integration else "mail@araz.me",
        },
    )

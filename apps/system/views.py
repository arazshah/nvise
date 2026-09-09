from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from apps.subscriptions.models import Subscription, UsageRecord
from apps.tenants.models import Tenant


@staff_member_required
def saas_dashboard(request):
    since = timezone.now() - timedelta(days=30)
    active_statuses = [Subscription.Status.ACTIVE, Subscription.Status.TRIALING]
    active_subscriptions = Subscription.objects.filter(status__in=active_statuses).select_related(
        "tenant", "plan"
    )
    mrr = active_subscriptions.aggregate(total=Sum("plan__monthly_price"))["total"] or 0
    usage = {
        row["metric"]: row["total"]
        for row in UsageRecord.objects.filter(occurred_at__gte=since)
        .values("metric")
        .annotate(total=Sum("quantity"))
    }
    tenant_rows = (
        Tenant.objects.annotate(
            active_members=Count("memberships", filter=Q(memberships__is_active=True))
        )
        .select_related("subscription__plan")
        .order_by("name")[:100]
    )
    subscription_status = list(
        Subscription.objects.values("status").annotate(total=Count("id")).order_by("status")
    )
    return render(
        request,
        "system/saas_dashboard.html",
        {
            "tenant_count": Tenant.objects.count(),
            "active_subscription_count": active_subscriptions.count(),
            "mrr": mrr,
            "usage": usage,
            "tenant_rows": tenant_rows,
            "subscription_status": subscription_status,
            "since": since,
        },
    )

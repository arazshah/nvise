from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.subscriptions.models import PaymentAttempt, Plan, UsageRecord
from apps.subscriptions.payments import PAYMENT_ROLES, PaymentError, create_and_send_invoice
from apps.subscriptions.services import refresh_subscription_state
from apps.system.models import IntegrationSettings


STATUS_LABELS = {
    "trialing": "دوره آزمایشی",
    "active": "فعال",
    "past_due": "نیازمند پیگیری پرداخت",
    "cancelled": "لغو شده",
    "expired": "منقضی شده",
}


def _billing_membership(user):
    return (
        user.tenant_memberships.select_related("tenant", "tenant__subscription__plan")
        .filter(is_active=True, tenant__is_active=True)
        .order_by("created_at")
        .first()
    )


@login_required
@require_http_methods(["GET"])
def billing_overview(request):
    integration = IntegrationSettings.objects.filter(pk=1).first()
    membership = _billing_membership(request.user)

    tenant = membership.tenant if membership else None
    subscription = refresh_subscription_state(tenant) if tenant else None
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
    can_manage_billing = bool(membership and membership.role in PAYMENT_ROLES)
    has_bale_identity = bool(
        getattr(request.user, "bale_identity", None)
        and request.user.bale_identity.is_active
        and request.user.bale_identity.external_chat_id
    )
    can_pay = bool(
        billing_visible
        and online_payment_enabled
        and payment_token_configured
        and can_manage_billing
        and has_bale_identity
    )

    recent_payments = (
        PaymentAttempt.objects.filter(tenant=tenant).select_related("plan", "user")[:8]
        if tenant
        else PaymentAttempt.objects.none()
    )
    is_trial = bool(plan and plan.code == "trial")
    trial_expired = bool(is_trial and subscription and subscription.status == "expired")

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
            "can_manage_billing": can_manage_billing,
            "has_bale_identity": has_bale_identity,
            "can_pay": can_pay,
            "recent_payments": recent_payments,
            "is_trial": is_trial,
            "trial_expired": trial_expired,
            "billing_notice": (
                integration.billing_notice
                if integration
                else "پرداخت اشتراک از طریق کیف پول بله انجام خواهد شد."
            ),
            "support_email": integration.support_email if integration else "mail@araz.me",
        },
    )


@login_required
@require_POST
def start_bale_checkout(request, plan_code: str):
    membership = _billing_membership(request.user)
    if membership is None:
        messages.error(request, "حساب فعالی برای خرید اشتراک پیدا نشد.")
        return redirect("portal:billing")

    plan = get_object_or_404(Plan, code=plan_code, is_active=True)
    try:
        create_and_send_invoice(user=request.user, tenant=membership.tenant, plan=plan)
    except PaymentError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            "صورتحساب به گفتگوی شما در بله ارسال شد. پرداخت را داخل بله تکمیل کنید؛ "
            "اشتراک فقط بعد از دریافت تأیید نهایی بله فعال یا تمدید می‌شود.",
        )
    return redirect("portal:billing")

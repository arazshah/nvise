from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.subscriptions.models import Plan, Subscription, UsageRecord
from apps.system.jalali import format_jalali
from apps.system.models import IntegrationSettings
from apps.tenants.models import Tenant, TenantMembership


@pytest.mark.django_db
def test_public_home_and_guide_reflect_current_product_identity(client):
    IntegrationSettings.objects.update_or_create(
        pk=1,
        defaults={
            "creator_name": "آراز شاه‌کرمی",
            "creator_url": "https://araz.me",
            "support_email": "mail@araz.me",
            "show_billing_portal": True,
            "billing_notice": "پرداخت اشتراک از طریق کیف پول بله انجام خواهد شد.",
        },
    )

    home = client.get("/")
    assert home.status_code == 200
    home_text = home.content.decode("utf-8")
    assert "آراز شاه‌کرمی" in home_text
    assert "mail@araz.me" in home_text
    assert "از اطلاعات پراکنده" in home_text
    assert "گزارش حرفه‌ای و قابل اتکا" in home_text
    assert "وکلا و دفاتر حقوقی" in home_text
    assert "کارشناسان رسمی" in home_text
    assert "کارشناسان بیمه و ارزیابان خسارت" in home_text
    assert "۳۰ روز" in home_text
    assert "/finish" not in home_text

    guide = client.get("/guide/")
    assert guide.status_code == 200
    guide_text = guide.content.decode("utf-8")
    assert "راهنمای ساده استفاده از نویسه" in guide_text
    assert "🏠 منوی اصلی" in guide_text
    assert "💳 اشتراک و مصرف" in guide_text
    assert "sendInvoice" not in guide_text
    assert "pre_checkout_query" not in guide_text
    assert "Admin" not in guide_text
    assert "زیبال" not in guide_text


@pytest.mark.django_db
def test_billing_portal_shows_plan_subscription_usage_and_jalali_dates(client):
    user = User.objects.create_user(username="billing-user")
    tenant = Tenant.objects.create(name="حساب شخصی", slug="billing-personal")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    plan = Plan.objects.create(
        code="pro-test",
        name="حرفه‌ای",
        monthly_price=990000,
        currency="IRR",
        max_cases_per_period=30,
        max_stt_seconds_per_period=7200,
        max_ai_extractions_per_period=100,
        max_members=3,
    )
    now = timezone.now()
    period_end = now + timedelta(days=29)
    Subscription.objects.create(
        tenant=tenant,
        plan=plan,
        status=Subscription.Status.ACTIVE,
        current_period_start=now - timedelta(days=1),
        current_period_end=period_end,
    )
    UsageRecord.objects.create(
        tenant=tenant,
        metric=UsageRecord.Metric.CASE_CREATED,
        quantity=2,
        idempotency_key="billing-test-cases",
    )
    settings_obj, _ = IntegrationSettings.objects.update_or_create(
        pk=1,
        defaults={
            "show_billing_portal": True,
            "online_payment_enabled": False,
            "payment_provider": IntegrationSettings.PaymentProvider.BALE,
            "billing_notice": "پرداخت اشتراک از طریق کیف پول بله انجام خواهد شد.",
            "support_email": "mail@araz.me",
        },
    )
    settings_obj.set_bale_payment_token("WALLET-TEST-1111111111111111")
    settings_obj.save(update_fields=["bale_payment_token_encrypted", "updated_at"])

    client.force_login(user)
    response = client.get("/review/billing/")
    assert response.status_code == 200
    text = response.content.decode("utf-8")
    assert "حرفه‌ای" in text
    assert "پرداخت از طریق بله" in text
    assert "پرداخت آنلاین فعلاً در دسترس نیست" in text
    assert format_jalali(timezone.localtime(period_end)) in text
    assert "2" in text
    assert settings_obj.bale_payment_token == "WALLET-TEST-1111111111111111"

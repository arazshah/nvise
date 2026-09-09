from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.accounts.models import BaleIdentity, User
from apps.messaging.tasks import (
    PLAN_ACTION_PREFIX,
    _handle_bale_plan_purchase,
    _show_billing_summary,
)
from apps.subscriptions.models import Plan, Subscription
from apps.tenants.models import Tenant, TenantMembership


class FakeProvider:
    def __init__(self):
        self.client = object()
        self.sent = []

    async def send_text(self, chat_id, text, keyboard=None):
        self.sent.append((chat_id, text, keyboard))
        return {"message_id": 1}


def _account():
    user = User.objects.create_user(username="bale-billing-menu")
    tenant = Tenant.objects.create(name="حساب تست بله", slug="bale-billing-menu")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    BaleIdentity.objects.create(
        user=user,
        external_user_id="1001",
        external_chat_id="2002",
    )
    trial = Plan.objects.create(
        code="trial-menu",
        name="آزمایشی",
        monthly_price=0,
        currency="IRR",
        max_cases_per_period=5,
        max_stt_seconds_per_period=1800,
        max_ai_extractions_per_period=15,
        max_members=1,
    )
    pro = Plan.objects.create(
        code="pro-menu",
        name="حرفه‌ای",
        monthly_price=490000,
        currency="IRR",
        max_cases_per_period=50,
        max_stt_seconds_per_period=18000,
        max_ai_extractions_per_period=150,
        max_members=1,
    )
    team = Plan.objects.create(
        code="team-menu",
        name="تیمی",
        monthly_price=1490000,
        currency="IRR",
        max_cases_per_period=200,
        max_stt_seconds_per_period=72000,
        max_ai_extractions_per_period=600,
        max_members=5,
    )
    now = timezone.now()
    Subscription.objects.create(
        tenant=tenant,
        plan=trial,
        status=Subscription.Status.TRIALING,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        metadata={"trial_granted": True},
    )
    return user, tenant, pro, team


@pytest.mark.django_db
def test_bale_billing_summary_lists_paid_plans_and_web_panel():
    user, _tenant, pro, team = _account()
    provider = FakeProvider()
    message = SimpleNamespace(external_chat_id="2002")

    _show_billing_summary(provider=provider, user=user, message=message)

    assert provider.sent
    _chat_id, text, keyboard = provider.sent[-1]
    assert "پلن‌های قابل خرید یا تمدید" in text
    assert "حرفه‌ای" in text
    assert "تیمی" in text
    labels = [button["text"] for row in keyboard["keyboard"] for button in row]
    assert any(label.startswith(f"{PLAN_ACTION_PREFIX}{pro.code}") for label in labels)
    assert any(label.startswith(f"{PLAN_ACTION_PREFIX}{team.code}") for label in labels)
    assert "🌐 ورود به پنل نویسه" in labels
    assert "🏠 منوی اصلی" in labels


@pytest.mark.django_db
def test_bale_plan_button_uses_shared_invoice_service(monkeypatch):
    user, tenant, pro, _team = _account()
    provider = FakeProvider()
    message = SimpleNamespace(external_chat_id="2002")
    called = {}

    def fake_invoice(*, user, tenant, plan):
        called.update(user=user, tenant=tenant, plan=plan)
        return SimpleNamespace(id="attempt-1")

    monkeypatch.setattr("apps.messaging.tasks.create_and_send_invoice", fake_invoice)
    _handle_bale_plan_purchase(
        provider=provider,
        user=user,
        message=message,
        message_text=f"{PLAN_ACTION_PREFIX}{pro.code} · خرید {pro.name}",
    )

    assert called["user"] == user
    assert called["tenant"] == tenant
    assert called["plan"] == pro
    assert "صورتحساب پلن" in provider.sent[-1][1]

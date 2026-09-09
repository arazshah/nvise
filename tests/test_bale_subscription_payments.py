from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import BaleIdentity, User
from apps.messaging.providers.bale.client import BaleClient
from apps.subscriptions.models import PaymentAttempt, Plan, Subscription
from apps.subscriptions.payments import (
    answer_precheckout,
    create_and_send_invoice,
    process_successful_payment,
    validate_precheckout,
)
from apps.system.models import IntegrationSettings
from apps.tenants.models import Tenant, TenantMembership


async def _fake_send_invoice(self, **kwargs):
    return {"message_id": 901, "invoice": kwargs}


async def _fake_answer_precheckout(self, **kwargs):
    return None


def _configure_bale_payments():
    integration, _ = IntegrationSettings.objects.get_or_create(pk=1)
    integration.bale_enabled = True
    integration.online_payment_enabled = True
    integration.payment_provider = IntegrationSettings.PaymentProvider.BALE
    integration.set_bale_bot_token("bot-token-for-test")
    integration.set_bale_payment_token("WALLET-TEST-1111111111111111")
    integration.save()
    return integration


def _account():
    user = User.objects.create_user(username="payer")
    tenant = Tenant.objects.create(name="حساب پرداخت", slug="payment-account")
    TenantMembership.objects.create(
        tenant=tenant,
        user=user,
        role=TenantMembership.Role.OWNER,
    )
    BaleIdentity.objects.create(
        user=user,
        external_user_id="11001",
        external_chat_id="22002",
        first_name="پرداخت",
    )
    plan = Plan.objects.create(
        code="paid-pro",
        name="حرفه‌ای",
        monthly_price=990000,
        currency="IRR",
        max_cases_per_period=100,
        max_stt_seconds_per_period=10000,
        max_ai_extractions_per_period=300,
        max_members=3,
    )
    return user, tenant, plan


@pytest.mark.django_db
def test_bale_payment_activates_subscription_once(monkeypatch):
    _configure_bale_payments()
    user, tenant, plan = _account()
    monkeypatch.setattr(BaleClient, "send_invoice", _fake_send_invoice)
    monkeypatch.setattr(BaleClient, "answer_pre_checkout_query", _fake_answer_precheckout)

    attempt = create_and_send_invoice(user=user, tenant=tenant, plan=plan)
    assert attempt.status == PaymentAttempt.Status.INVOICE_SENT
    assert attempt.amount == 990000
    assert attempt.invoice_message_id == "901"

    precheckout = {
        "id": "bale-txn-001",
        "from": {"id": 11001},
        "currency": "IRR",
        "total_amount": 990000,
        "invoice_payload": attempt.payload,
    }
    assert answer_precheckout(precheckout) is True
    attempt.refresh_from_db()
    assert attempt.status == PaymentAttempt.Status.PRECHECKOUT_APPROVED
    assert attempt.pre_checkout_query_id == "bale-txn-001"

    successful_message = {
        "from": {"id": 11001},
        "successful_payment": {
            "currency": "IRR",
            "total_amount": 990000,
            "invoice_payload": attempt.payload,
            "telegram_payment_charge_id": "bale-txn-001",
            "provider_payment_charge_id": "tracking-001",
        },
    }
    paid_attempt, subscription, activated = process_successful_payment(successful_message)
    assert activated is True
    assert paid_attempt.status == PaymentAttempt.Status.PAID
    assert subscription.plan == plan
    assert subscription.status == Subscription.Status.ACTIVE
    first_end = subscription.current_period_end
    assert first_end > timezone.now() + timedelta(days=29)

    _, replay_subscription, replay_activated = process_successful_payment(successful_message)
    assert replay_activated is False
    assert replay_subscription.current_period_end == first_end


@pytest.mark.django_db
def test_precheckout_rejects_amount_mismatch(monkeypatch):
    _configure_bale_payments()
    user, tenant, plan = _account()
    monkeypatch.setattr(BaleClient, "send_invoice", _fake_send_invoice)

    attempt = create_and_send_invoice(user=user, tenant=tenant, plan=plan)
    ok, error, checked = validate_precheckout(
        {
            "id": "bad-amount-1",
            "from": {"id": 11001},
            "currency": "IRR",
            "total_amount": 1,
            "invoice_payload": attempt.payload,
        }
    )
    assert ok is False
    assert error
    assert checked is not None
    checked.refresh_from_db()
    assert checked.status == PaymentAttempt.Status.REJECTED
    assert "مبلغ" in checked.failure_reason
    assert not Subscription.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_billing_checkout_sends_invoice_to_linked_bale_chat(client, monkeypatch):
    _configure_bale_payments()
    user, _tenant, plan = _account()
    monkeypatch.setattr(BaleClient, "send_invoice", _fake_send_invoice)
    client.force_login(user)

    response = client.post(f"/review/billing/checkout/{plan.code}/")
    assert response.status_code == 302
    attempt = PaymentAttempt.objects.get(plan=plan)
    assert attempt.external_user_id == "11001"
    assert attempt.external_chat_id == "22002"
    assert attempt.status == PaymentAttempt.Status.INVOICE_SENT

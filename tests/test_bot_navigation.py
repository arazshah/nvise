from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.cases.services import create_case
from apps.intelligence.followups import follow_up_keyboard
from apps.intelligence.results import analysis_result_keyboard
from apps.messaging.handlers import handle_message
from apps.messaging.models import ConversationState, InboundUpdate
from apps.tenants.models import Tenant, TenantMembership


def _labels(keyboard):
    return {
        button["text"]
        for row in keyboard.get("keyboard", [])
        for button in row
        if isinstance(button, dict) and button.get("text")
    }


@pytest.mark.django_db
def test_analysis_and_followup_keyboards_always_offer_global_navigation():
    user = User.objects.create_user(username="navigation-user")
    tenant = Tenant.objects.create(name="Navigation", slug="navigation")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="Navigation case")

    expected = {"🏠 منوی اصلی", "➕ پرونده جدید", "📂 پرونده‌های من"}
    assert expected <= _labels(analysis_result_keyboard(case))
    assert expected <= _labels(follow_up_keyboard())


@pytest.mark.django_db
def test_home_menu_exits_case_context_without_archiving_case():
    user = User.objects.create_user(username="home-menu-user")
    tenant = Tenant.objects.create(name="Home Menu", slug="home-menu")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="Keep me")
    state = ConversationState.objects.create(
        user=user,
        provider="bale",
        external_chat_id="home-chat",
        active_case=case,
        state="awaiting_followup",
        pending_action={"follow_up_question_id": "ignored"},
    )
    inbound = InboundUpdate.objects.create(
        provider="bale",
        bot_id="primary",
        external_update_id="home-navigation-1",
        payload={},
    )
    message = SimpleNamespace(
        provider="bale",
        external_chat_id="home-chat",
        external_message_id="home-message-1",
        message_type="text",
        text="🏠 منوی اصلی",
        raw={},
        sent_at=None,
        file=None,
    )
    provider = SimpleNamespace(client=None)

    handle_message(inbound=inbound, provider=provider, user=user, message=message)

    state.refresh_from_db()
    case.refresh_from_db()
    assert state.active_case_id is None
    assert state.state == "idle"
    assert state.pending_action == {}
    assert case.lifecycle_status == case.LifecycleStatus.ACTIVE

from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.cases.services import create_case
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.followups import UNAVAILABLE_LABEL, record_follow_up_answer
from apps.intelligence.models import CaseFieldIssue, FollowUpQuestion
from apps.messaging.models import ConversationState, InboundUpdate
from apps.tenants.models import Tenant, TenantMembership


def _setup_followup():
    user = User.objects.create_user(username="followup-user")
    tenant = Tenant.objects.create(name="Followup", slug="followup-test")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده تست")
    schema = ensure_fire_loss_schema()
    field = schema.fields.filter(required=True).first()
    issue = CaseFieldIssue.objects.create(
        case=case,
        field=field,
        issue_type=CaseFieldIssue.IssueType.MISSING,
        details={"reason": "required_field_not_extracted"},
    )
    question = FollowUpQuestion.objects.create(
        case=case,
        issue=issue,
        question_text="سؤال تست",
        status=FollowUpQuestion.Status.ASKED,
    )
    state = ConversationState.objects.create(
        user=user,
        provider="bale",
        external_chat_id="100",
        active_case=case,
        state="awaiting_followup",
        pending_action={"follow_up_question_id": str(question.id)},
    )
    inbound = InboundUpdate.objects.create(
        provider="bale",
        bot_id="primary",
        external_update_id="1",
        payload={},
    )
    return user, issue, question, state, inbound


@pytest.mark.django_db
def test_text_answer_does_not_resolve_issue_before_reanalysis():
    user, issue, question, state, inbound = _setup_followup()
    message = SimpleNamespace(
        provider="bale",
        external_chat_id="100",
        external_message_id="200",
        message_type="text",
        text="پاسخ کاربر",
        raw={},
        sent_at=None,
    )

    record_follow_up_answer(state=state, inbound=inbound, user=user, message=message)

    issue.refresh_from_db()
    question.refresh_from_db()
    assert issue.status == CaseFieldIssue.Status.OPEN
    assert issue.attempt_count == 1
    assert issue.resolution_note == "پاسخ کاربر"
    assert question.status == FollowUpQuestion.Status.ANSWERED
    assert question.answer_evidence_id is not None


@pytest.mark.django_db
def test_unavailable_answer_closes_issue_without_reasking():
    user, issue, question, state, inbound = _setup_followup()
    message = SimpleNamespace(
        provider="bale",
        external_chat_id="100",
        external_message_id="201",
        message_type="text",
        text=UNAVAILABLE_LABEL,
        raw={},
        sent_at=None,
    )

    record_follow_up_answer(state=state, inbound=inbound, user=user, message=message)

    issue.refresh_from_db()
    question.refresh_from_db()
    assert issue.status == CaseFieldIssue.Status.UNAVAILABLE
    assert issue.resolved_at is not None
    assert question.status == FollowUpQuestion.Status.CANCELLED

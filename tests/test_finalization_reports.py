from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.cases.models import Case
from apps.cases.services import create_case, finish_input, transition_case
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.followups import ensure_follow_up_questions, record_follow_up_answer
from apps.intelligence.models import CaseFieldIssue, ExtractedFact, ExtractionRun, FollowUpQuestion
from apps.messaging.models import ConversationState, InboundUpdate
from apps.reports.models import Report
from apps.reports.services import approve_report, generate_report_revision
from apps.tenants.models import Tenant, TenantMembership


def _case_fixture():
    user = User.objects.create_user(username="reviewer")
    tenant = Tenant.objects.create(name="Personal", slug="personal-finalization")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="Fire loss")
    return user, case


@pytest.mark.django_db
def test_follow_up_answer_is_linked_to_issue_evidence():
    user, case = _case_fixture()
    case = finish_input(case=case, actor=user)
    case = transition_case(case=case, target_status=Case.Status.NEEDS_INFORMATION, actor=user)
    schema = ensure_fire_loss_schema()
    field = schema.fields.get(key="incident_address")
    issue = CaseFieldIssue.objects.create(
        case=case,
        field=field,
        issue_type=CaseFieldIssue.IssueType.MISSING,
    )
    question = ensure_follow_up_questions(case)[0]
    state = ConversationState.objects.create(
        user=user,
        provider="bale",
        external_chat_id="chat-1",
        active_case=case,
        state="awaiting_followup",
        pending_action={"follow_up_question_id": str(question.id)},
    )
    inbound = InboundUpdate.objects.create(
        provider="bale",
        bot_id="primary",
        external_update_id="followup-1",
        payload={},
    )
    message = SimpleNamespace(
        provider="bale",
        external_chat_id="chat-1",
        external_message_id="message-1",
        message_type="text",
        text="تهران، خیابان نمونه، پلاک ۱۰",
        raw={},
        sent_at=None,
    )

    answered = record_follow_up_answer(
        state=state,
        inbound=inbound,
        user=user,
        message=message,
    )

    issue.refresh_from_db()
    answered.refresh_from_db()
    assert issue.status == CaseFieldIssue.Status.OPEN
    assert issue.attempt_count == 1
    assert issue.resolution_note == "تهران، خیابان نمونه، پلاک ۱۰"
    assert answered.status == FollowUpQuestion.Status.ANSWERED
    assert answered.answer_evidence is not None
    assert answered.answer_evidence.text == "تهران، خیابان نمونه، پلاک ۱۰"


@pytest.mark.django_db
def test_report_revision_and_approval_transition_case():
    user, case = _case_fixture()
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(
        case=case,
        schema=schema,
        provider="test",
        status=ExtractionRun.Status.COMPLETED,
    )
    field = schema.fields.get(key="insured_name")
    ExtractedFact.objects.create(
        case=case,
        field=field,
        extraction_run=run,
        value="آراز شاهکرمی",
        normalized_value="آراز شاهکرمی",
        confidence=0.98,
    )
    case = finish_input(case=case, actor=user)
    case = transition_case(case=case, target_status=Case.Status.READY_FOR_REVIEW, actor=user)

    revision = generate_report_revision(case=case, created_by=user)
    assert revision.revision_number == 1
    assert revision.sections.count() == 5
    assert revision.sections.filter(key="limitations").exists()
    assert revision.structured_data["facts"]["insured_name"]["value"] == "آراز شاهکرمی"

    report = approve_report(case=case, user=user)
    case.refresh_from_db()
    assert report.status == Report.Status.APPROVED
    assert case.status == Case.Status.APPROVED
    assert report.approvals.count() == 1

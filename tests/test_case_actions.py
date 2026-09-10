import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.cases.actions import (
    complete_case_action,
    create_manual_action,
    next_best_action,
    sync_system_actions,
)
from apps.cases.models import Case, CaseAction
from apps.cases.services import create_case
from apps.messaging.models import CaseMessage
from apps.tenants.models import Tenant, TenantMembership


def _case():
    user = User.objects.create_user(username="habit-user")
    tenant = Tenant.objects.create(name="Habit", slug="habit")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده پیگیری")
    return user, case


@pytest.mark.django_db
def test_next_best_action_follows_case_workflow():
    user, case = _case()
    assert next_best_action(case) is None

    CaseMessage.objects.create(
        user=user,
        case=case,
        assignment_status=CaseMessage.AssignmentStatus.ASSIGNED,
        provider="bale",
        external_chat_id="habit-chat",
        external_message_id="habit-1",
        message_type=CaseMessage.MessageType.TEXT,
        text="مدرک اولیه ثبت شد.",
    )
    action = next_best_action(case)
    assert action.action_type == CaseAction.ActionType.START_ANALYSIS
    assert action.title == "تحلیل پرونده را شروع کنید"

    case.analysis_status = Case.AnalysisStatus.NEEDS_REVIEW
    case.save(update_fields=["analysis_status", "updated_at"])
    action = next_best_action(case)
    assert action.action_type == CaseAction.ActionType.REVIEW_ANALYSIS

    case.analysis_status = Case.AnalysisStatus.COMPLETED
    case.report_status = Case.ReportStatus.NOT_CREATED
    case.save(update_fields=["analysis_status", "report_status", "updated_at"])
    action = next_best_action(case)
    assert action.action_type == CaseAction.ActionType.GENERATE_REPORT

    case.report_status = Case.ReportStatus.READY_FOR_REVIEW
    case.save(update_fields=["report_status", "updated_at"])
    action = next_best_action(case)
    assert action.action_type == CaseAction.ActionType.REVIEW_REPORT

    open_system = CaseAction.objects.filter(case=case, system_key__gt="", status=CaseAction.Status.OPEN)
    assert open_system.count() == 1


@pytest.mark.django_db
def test_manual_action_can_be_completed_and_outranks_normal_system_action():
    user, case = _case()
    CaseMessage.objects.create(
        user=user,
        case=case,
        assignment_status=CaseMessage.AssignmentStatus.ASSIGNED,
        provider="bale",
        external_chat_id="habit-chat-2",
        external_message_id="habit-2",
        message_type=CaseMessage.MessageType.TEXT,
        text="پرونده آماده تحلیل است.",
    )
    sync_system_actions(case)
    manual = create_manual_action(
        case=case,
        user=user,
        title="دریافت فاکتور تعمیرات",
        description="از بیمه‌گذار پیگیری شود.",
        due_at=timezone.now(),
    )
    manual.priority = CaseAction.Priority.HIGH
    manual.save(update_fields=["priority", "updated_at"])

    action = next_best_action(case)
    assert action.action_id == str(manual.id)

    complete_case_action(case=case, action_id=manual.id, user=user)
    manual.refresh_from_db()
    assert manual.status == CaseAction.Status.DONE
    assert manual.completed_at is not None
    assert next_best_action(case).action_type == CaseAction.ActionType.START_ANALYSIS


@pytest.mark.django_db
def test_case_repository_exposes_manual_actions_and_next_action(client):
    user, case = _case()
    CaseMessage.objects.create(
        user=user,
        case=case,
        assignment_status=CaseMessage.AssignmentStatus.ASSIGNED,
        provider="bale",
        external_chat_id="habit-chat-3",
        external_message_id="habit-3",
        message_type=CaseMessage.MessageType.TEXT,
        text="شروع پرونده.",
    )
    create_manual_action(case=case, user=user, title="تماس با بیمه‌گذار")
    client.force_login(user)

    response = client.get(f"/review/cases/{case.case_code}/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "اقدام بعدی پیشنهادی" in body
    assert "تماس با بیمه‌گذار" in body
    assert "کارهای این پرونده" in body

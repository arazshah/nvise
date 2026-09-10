from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.cases.action_suggestions import accept_action_suggestion, generate_action_suggestions
from apps.cases.actions import create_manual_action, sync_system_actions
from apps.cases.digests import daily_digest_text
from apps.cases.models import (
    Case,
    CaseAction,
    CaseActionSuggestion,
    CaseReminder,
    ReminderPreference,
)
from apps.cases.reminders import claim_due_reminders
from apps.cases.services import create_case
from apps.evidence.models import Evidence
from apps.messaging.models import CaseMessage
from apps.tenants.models import Tenant, TenantMembership


def _setup_case(username="habit-pro"):
    user = User.objects.create_user(username=username)
    tenant = Tenant.objects.create(name=f"Tenant {username}", slug=f"tenant-{username}")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده پیگیری")
    return user, case


@pytest.mark.django_db
def test_due_manual_action_creates_reminder_and_due_claim():
    user, case = _setup_case("reminder-user")
    ReminderPreference.objects.create(
        user=user,
        reminders_enabled=True,
        quiet_start="00:00",
        quiet_end="00:00",
    )
    action = create_manual_action(
        case=case,
        user=user,
        title="دریافت فاکتور",
        due_at=timezone.now() - timezone.timedelta(minutes=1),
    )
    reminder = CaseReminder.objects.get(action=action)
    assert reminder.status == CaseReminder.Status.PENDING

    claimed = claim_due_reminders()
    assert [row.id for row in claimed] == [reminder.id]
    reminder.refresh_from_db()
    assert reminder.status == CaseReminder.Status.DISPATCHING


@pytest.mark.django_db
def test_report_review_action_schedules_delayed_reminder():
    user, case = _setup_case("report-reminder")
    ReminderPreference.objects.create(
        user=user,
        reminders_enabled=True,
        report_review_enabled=True,
        quiet_start="00:00",
        quiet_end="00:00",
    )
    case.report_status = Case.ReportStatus.READY_FOR_REVIEW
    case.analysis_status = Case.AnalysisStatus.COMPLETED
    case.save(update_fields=["report_status", "analysis_status", "updated_at"])

    rows = sync_system_actions(case)
    review_action = next(row for row in rows if row.action_type == CaseAction.ActionType.REVIEW_REPORT)
    reminder = CaseReminder.objects.get(action=review_action)
    assert reminder.remind_at > timezone.now()


@pytest.mark.django_db
def test_today_page_and_daily_digest_surface_real_actions(client):
    user, case = _setup_case("today-user")
    ReminderPreference.objects.create(
        user=user,
        reminders_enabled=True,
        daily_digest_enabled=True,
        quiet_start="00:00",
        quiet_end="00:00",
    )
    create_manual_action(
        case=case,
        user=user,
        title="تماس با بیمه‌گذار",
        due_at=timezone.now(),
    )
    client.force_login(user)
    response = client.get("/review/today/")
    assert response.status_code == 200
    assert "تماس با بیمه‌گذار" in response.content.decode("utf-8")

    text, count = daily_digest_text(user)
    assert count >= 1
    assert "تماس با بیمه‌گذار" in text


@pytest.mark.django_db
def test_evidence_grounded_suggestion_requires_user_acceptance(monkeypatch):
    user, case = _setup_case("suggestion-user")
    user.profession_key = User.Profession.INSURANCE_LOSS_ADJUSTER
    user.specialty_key = "property_fire"
    user.save(update_fields=["profession_key", "specialty_key", "updated_at"])
    message = CaseMessage.objects.create(
        user=user,
        case=case,
        assignment_status=CaseMessage.AssignmentStatus.ASSIGNED,
        provider="bale",
        external_chat_id="suggestion-chat",
        external_message_id="suggestion-message",
        message_type=CaseMessage.MessageType.TEXT,
        text="بیمه‌گذار گفت فاکتور تعمیرات را فردا ارسال می‌کند.",
    )
    evidence = Evidence.objects.create(
        case=case,
        source_kind=Evidence.SourceKind.MESSAGE,
        message=message,
        text=message.text,
    )

    monkeypatch.setattr(
        "apps.cases.action_suggestions.get_avalai_config",
        lambda: SimpleNamespace(
            enabled=True,
            api_key="test-key",
            base_url="https://example.invalid/v1",
            text_model="test-model",
            timeout_seconds=5,
        ),
    )
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "model": "test-model",
        "choices": [
            {
                "message": {
                    "content": (
                        '{"suggestions":[{"title_fa":"پیگیری دریافت فاکتور تعمیرات",'
                        '"description_fa":"دریافت فاکتور از بیمه‌گذار پیگیری شود.",'
                        '"rationale_fa":"در پیام پرونده وعده ارسال فاکتور ثبت شده است.",'
                        f'"evidence_ids":["{evidence.id}"],"confidence":0.94,"due_at":null}}]'
                        "}"
                    )
                }
            }
        ],
    }
    monkeypatch.setattr("apps.cases.action_suggestions.httpx.post", lambda *args, **kwargs: response)

    created = generate_action_suggestions(case)
    assert len(created) == 1
    suggestion = created[0]
    assert suggestion.status == CaseActionSuggestion.Status.PROPOSED
    assert CaseAction.objects.filter(case=case, title=suggestion.title).exists() is False

    action = accept_action_suggestion(suggestion=suggestion, user=user)
    suggestion.refresh_from_db()
    assert suggestion.status == CaseActionSuggestion.Status.ACCEPTED
    assert action.source_event == "ai.suggestion"
    assert str(evidence.id) in action.metadata["source_evidence_ids"]

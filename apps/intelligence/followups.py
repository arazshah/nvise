from asgiref.sync import async_to_sync
from django.db import transaction
from django.utils import timezone

from apps.cases.models import Case
from apps.evidence.services import sync_message_evidence
from apps.messaging.models import CaseMessage, ConversationState
from apps.messaging.providers.bale import BaleProvider
from apps.system.integrations import get_bale_config

from .models import CaseFieldIssue, FollowUpQuestion


def _question_text(issue: CaseFieldIssue) -> str:
    if issue.issue_type == CaseFieldIssue.IssueType.MISSING:
        return f"لطفاً «{issue.field.label}» را مشخص کنید."
    if issue.issue_type == CaseFieldIssue.IssueType.CONFLICT:
        return f"برای «{issue.field.label}» اطلاعات متناقض ثبت شده است. لطفاً مقدار صحیح را تأیید کنید."
    return f"لطفاً مقدار معتبر برای «{issue.field.label}» ارائه کنید."


@transaction.atomic
def ensure_follow_up_questions(case: Case) -> list[FollowUpQuestion]:
    questions = []
    issues = (
        CaseFieldIssue.objects.filter(case=case, status=CaseFieldIssue.Status.OPEN)
        .select_related("field")
        .order_by("field__sequence", "created_at")
    )
    for issue in issues:
        question, _ = FollowUpQuestion.objects.get_or_create(
            issue=issue,
            defaults={"case": case, "question_text": _question_text(issue)},
        )
        questions.append(question)
    return questions


def next_pending_question(case: Case) -> FollowUpQuestion | None:
    return (
        FollowUpQuestion.objects.filter(
            case=case,
            status__in=[FollowUpQuestion.Status.PENDING, FollowUpQuestion.Status.ASKED],
        )
        .select_related("issue__field")
        .order_by("issue__field__sequence", "created_at")
        .first()
    )


def send_next_follow_up(case: Case) -> FollowUpQuestion | None:
    question = next_pending_question(case)
    if question is None:
        return None
    state = (
        ConversationState.objects.filter(active_case=case, provider="bale")
        .select_related("user")
        .order_by("-updated_at")
        .first()
    )
    bale = get_bale_config()
    if state is None or not bale.enabled or not bale.bot_token:
        return question
    provider = BaleProvider(bale.bot_token)
    async_to_sync(provider.send_text)(
        state.external_chat_id,
        f"برای تکمیل پرونده «{case.title or case.case_code}»:\n\n{question.question_text}",
    )
    question.status = FollowUpQuestion.Status.ASKED
    question.asked_at = timezone.now()
    question.save(update_fields=["status", "asked_at"])
    state.state = "awaiting_followup"
    state.pending_action = {"follow_up_question_id": str(question.id)}
    state.save(update_fields=["state", "pending_action", "updated_at"])
    return question


@transaction.atomic
def record_follow_up_answer(*, state: ConversationState, inbound, user, message) -> FollowUpQuestion:
    question_id = state.pending_action.get("follow_up_question_id")
    question = (
        FollowUpQuestion.objects.select_for_update()
        .select_related("case", "issue")
        .get(pk=question_id, case=state.active_case)
    )
    external_message_id = message.external_message_id or f"update-{inbound.external_update_id}"
    case_message, _ = CaseMessage.objects.get_or_create(
        provider=message.provider,
        external_chat_id=message.external_chat_id,
        external_message_id=external_message_id,
        defaults={
            "inbound_update": inbound,
            "user": user,
            "case": question.case,
            "assignment_status": CaseMessage.AssignmentStatus.ASSIGNED,
            "message_type": message.message_type,
            "text": message.text or "",
            "raw_payload": message.raw or {},
            "sent_at": message.sent_at,
        },
    )
    evidence = sync_message_evidence(case_message)
    if evidence is None:
        raise ValueError("Follow-up answer must contain text")
    question.answer_evidence = evidence
    question.status = FollowUpQuestion.Status.ANSWERED
    question.answered_at = timezone.now()
    question.save(update_fields=["answer_evidence", "status", "answered_at"])
    question.issue.status = CaseFieldIssue.Status.RESOLVED
    question.issue.resolved_at = timezone.now()
    question.issue.save(update_fields=["status", "resolved_at"])
    state.state = "idle"
    state.pending_action = {}
    state.save(update_fields=["state", "pending_action", "updated_at"])
    return question

from asgiref.sync import async_to_sync
from django.db import transaction
from django.utils import timezone

from apps.cases.models import Case
from apps.evidence.services import sync_message_evidence
from apps.messaging.models import CaseMessage, ConversationState
from apps.messaging.providers.bale import BaleProvider
from apps.system.integrations import get_bale_config

from .models import CaseFieldIssue, FollowUpQuestion
from .question_planner import plan_question


MAX_FOLLOW_UP_ATTEMPTS = 2
UNAVAILABLE_LABEL = "🚫 این اطلاعات در دسترس نیست"
WAIVE_LABEL = "⏭ با اطلاعات فعلی ادامه بده"
HOME_MENU_LABEL = "🏠 منوی اصلی"
NEW_CASE_LABEL = "➕ پرونده جدید"
MY_CASES_LABEL = "📂 پرونده‌های من"


def _question_text(issue: CaseFieldIssue) -> str:
    plan = plan_question(issue)
    lines = [f"🧠 {plan.title}", "", plan.explanation]
    if plan.sources:
        lines.extend(["", "🔗 شواهد مرتبط:"])
        lines.extend(f"• {source}" for source in plan.sources)
    if plan.candidates:
        lines.extend(["", "📌 مقادیر پیدا شده:"])
        lines.extend(f"• {candidate}" for candidate in plan.candidates)
    if plan.prompt:
        lines.extend(["", f"❓ {plan.prompt}"])
    if issue.resolution_note:
        lines.extend(["", f"پاسخ قبلی شما: {issue.resolution_note}"])
    if issue.attempt_count >= MAX_FOLLOW_UP_ATTEMPTS:
        lines.extend(
            [
                "",
                "این موضوع قبلاً دو بار بررسی شده است. برای جلوگیری از تکرار بی‌پایان، "
                "اگر پاسخ قطعی در دسترس نیست یکی از گزینه‌های پایین را انتخاب کنید.",
            ]
        )
    return "\n".join(line for line in lines if line is not None).strip()


def follow_up_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": UNAVAILABLE_LABEL}],
            [{"text": WAIVE_LABEL}],
            [{"text": NEW_CASE_LABEL}, {"text": MY_CASES_LABEL}],
            [{"text": HOME_MENU_LABEL}],
        ],
        "resize_keyboard": True,
    }


def _store_answer_evidence(*, question, inbound, user, message):
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
    return evidence


@transaction.atomic
def ensure_follow_up_questions(case: Case) -> list[FollowUpQuestion]:
    questions = []
    issues = list(
        CaseFieldIssue.objects.select_for_update()
        .filter(case=case, status=CaseFieldIssue.Status.OPEN)
        .select_related("field")
        .order_by("field__sequence", "created_at")
    )
    now = timezone.now()
    for issue in issues:
        plan = plan_question(issue)
        issue.details = {
            **(issue.details or {}),
            "planner_category": plan.category,
            "planner_title": plan.title,
            "planner_sources": list(plan.sources),
            "planner_candidates": list(plan.candidates),
        }
        if not plan.should_ask:
            issue.status = CaseFieldIssue.Status.RESOLVED
            issue.resolved_at = now
            issue.resolution_note = plan.explanation[:1000]
            issue.save(
                update_fields=["details", "status", "resolved_at", "resolution_note"]
            )
            FollowUpQuestion.objects.filter(issue=issue).update(
                status=FollowUpQuestion.Status.CANCELLED,
                answered_at=now,
            )
            continue

        issue.save(update_fields=["details"])
        question, created = FollowUpQuestion.objects.get_or_create(
            issue=issue,
            defaults={"case": case, "question_text": _question_text(issue)},
        )
        if not created:
            question.question_text = _question_text(issue)
            if question.status == FollowUpQuestion.Status.ANSWERED:
                question.status = FollowUpQuestion.Status.PENDING
                question.asked_at = None
                question.answered_at = None
                question.answer_evidence = None
            question.save(
                update_fields=["question_text", "status", "asked_at", "answered_at", "answer_evidence"]
            )
        questions.append(question)
    return questions


def next_pending_question(case: Case) -> FollowUpQuestion | None:
    return (
        FollowUpQuestion.objects.filter(
            case=case,
            issue__status=CaseFieldIssue.Status.OPEN,
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

    open_questions = FollowUpQuestion.objects.filter(
        case=case,
        issue__status=CaseFieldIssue.Status.OPEN,
    )
    total = open_questions.count()
    before = open_questions.filter(issue__field__sequence__lt=question.issue.field.sequence).count()
    number = min(before + 1, total) if total else 1

    provider = BaleProvider(bale.bot_token)
    async_to_sync(provider.send_text)(
        state.external_chat_id,
        f"🧩 بررسی تخصصی پرونده\n"
        f"━━━━━━━━━━━━━━\n"
        f"📝 {case.title or case.case_code}\n"
        f"❓ مورد {number} از {total or 1}\n\n"
        f"{question.question_text}\n\n"
        "✍️ می‌توانید پاسخ را بنویسید یا یکی از گزینه‌های زیر را انتخاب کنید.\n"
        "نویسه فقط مواردی را می‌پرسد که پس از بررسی شواهد هنوز به تصمیم شما نیاز دارند.",
        follow_up_keyboard(),
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
    answer_text = (message.text or "").strip()
    now = timezone.now()

    if answer_text == UNAVAILABLE_LABEL:
        question.issue.status = CaseFieldIssue.Status.UNAVAILABLE
        question.issue.resolution_note = "کاربر اعلام کرد این اطلاعات در دسترس نیست."
        question.issue.resolved_at = now
        question.issue.save(update_fields=["status", "resolution_note", "resolved_at"])
        question.status = FollowUpQuestion.Status.CANCELLED
        question.answered_at = now
        question.save(update_fields=["status", "answered_at"])
    elif answer_text == WAIVE_LABEL:
        question.issue.status = CaseFieldIssue.Status.WAIVED
        question.issue.resolution_note = "کاربر خواست با اطلاعات فعلی ادامه داده شود."
        question.issue.resolved_at = now
        question.issue.save(update_fields=["status", "resolution_note", "resolved_at"])
        question.status = FollowUpQuestion.Status.CANCELLED
        question.answered_at = now
        question.save(update_fields=["status", "answered_at"])
    else:
        evidence = _store_answer_evidence(
            question=question,
            inbound=inbound,
            user=user,
            message=message,
        )
        question.answer_evidence = evidence
        question.status = FollowUpQuestion.Status.ANSWERED
        question.answered_at = now
        question.save(update_fields=["answer_evidence", "status", "answered_at"])

        if question.issue.attempt_count >= MAX_FOLLOW_UP_ATTEMPTS:
            question.issue.status = CaseFieldIssue.Status.WAIVED
            question.issue.resolution_note = (
                f"آخرین پاسخ کاربر: {answer_text[:800]} — پس از {MAX_FOLLOW_UP_ATTEMPTS} تلاش ناموفق، "
                "برای جلوگیری از تکرار سؤال با اطلاعات فعلی ادامه داده شد."
            )
            question.issue.resolved_at = now
            question.issue.save(update_fields=["status", "resolution_note", "resolved_at"])
        else:
            question.issue.attempt_count += 1
            question.issue.resolution_note = answer_text[:1000]
            question.issue.save(update_fields=["attempt_count", "resolution_note"])

    state.state = "idle"
    state.pending_action = {}
    state.save(update_fields=["state", "pending_action", "updated_at"])
    return question

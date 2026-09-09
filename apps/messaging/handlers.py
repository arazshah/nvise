from asgiref.sync import async_to_sync
from django.db import transaction

from apps.cases.models import Case
from apps.cases.presentation import case_status_description, case_status_label
from apps.cases.services import CaseTransitionError, create_case, finish_input, transition_case
from apps.evidence.services import sync_message_evidence
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.followups import (
    next_pending_question,
    record_follow_up_answer,
    send_next_follow_up,
)
from apps.intelligence.services import start_extraction
from apps.processing.models import ProcessingJob
from apps.processing.services import ensure_attachment_job
from apps.processing.tasks import fetch_attachment
from apps.reports.services import approve_report
from apps.tenants.models import TenantMembership

from .models import CaseMessage, ConversationState, InboundUpdate


NEW_CASE_COMMANDS = {"/newcase", "پرونده جدید", "➕ پرونده جدید"}
CASES_COMMANDS = {"/cases", "پرونده‌های باز", "📂 پرونده‌های باز"}
ACTIVE_COMMANDS = {"/active", "پرونده فعال"}
STATUS_COMMANDS = {"/status", "وضعیت", "📊 وضعیت"}
FINISH_COMMANDS = {"/finish", "پایان ورود اطلاعات", "✅ پایان ورود اطلاعات"}
APPROVE_COMMANDS = {"/approve", "تأیید گزارش", "✅ تأیید گزارش"}


def send_text(provider, chat_id: str, text: str, keyboard: dict | None = None) -> None:
    if getattr(provider, "client", None) is None:
        return
    async_to_sync(provider.send_text)(chat_id, text, keyboard)


def main_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": "➕ پرونده جدید"}, {"text": "📂 پرونده‌های باز"}],
            [{"text": "📊 وضعیت"}],
        ],
        "resize_keyboard": True,
    }


def _user_primary_tenant(user):
    membership = (
        TenantMembership.objects.select_related("tenant")
        .filter(user=user, is_active=True, tenant__is_active=True)
        .order_by("created_at")
        .first()
    )
    if membership is None:
        raise RuntimeError("User has no active tenant membership")
    return membership.tenant


def _record_message(*, inbound: InboundUpdate, user, state: ConversationState, message) -> CaseMessage:
    active_case = state.active_case
    can_assign = active_case is not None and active_case.status in {Case.Status.DRAFT, Case.Status.OPEN}
    external_message_id = message.external_message_id or f"update-{inbound.external_update_id}"
    case_message, _ = CaseMessage.objects.get_or_create(
        provider=message.provider,
        external_chat_id=message.external_chat_id,
        external_message_id=external_message_id,
        defaults={
            "inbound_update": inbound,
            "user": user,
            "case": active_case if can_assign else None,
            "assignment_status": (
                CaseMessage.AssignmentStatus.ASSIGNED
                if can_assign
                else CaseMessage.AssignmentStatus.UNASSIGNED
            ),
            "message_type": message.message_type,
            "text": message.text or "",
            "raw_payload": message.raw or {},
            "sent_at": message.sent_at,
        },
    )
    return case_message


def _enqueue_attachment_if_present(*, stored: CaseMessage, message) -> None:
    if message.file is None or not message.file.file_id:
        return
    attachment = ensure_attachment_job(message=stored, normalized_file=message.file)
    fetch_job = attachment.jobs.filter(job_type=ProcessingJob.JobType.FETCH_ATTACHMENT).first()
    if fetch_job is not None and fetch_job.status == ProcessingJob.Status.PENDING:
        transaction.on_commit(lambda: fetch_attachment.delay(str(fetch_job.id)))


def _handle_follow_up_answer(*, state, inbound, provider, user, message) -> bool:
    if state.state != "awaiting_followup" or state.active_case is None:
        return False
    if state.active_case.status != Case.Status.NEEDS_INFORMATION:
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["state", "pending_action", "updated_at"])
        return False
    if message.message_type != CaseMessage.MessageType.TEXT or not (message.text or "").strip():
        send_text(
            provider,
            message.external_chat_id,
            "✍️ برای پاسخ به سؤال تکمیلی، لطفاً پاسخ را فعلاً به‌صورت متن ارسال کنید.",
        )
        return True

    question = record_follow_up_answer(
        state=state,
        inbound=inbound,
        user=user,
        message=message,
    )
    case = question.case
    if next_pending_question(case) is not None:
        send_text(provider, message.external_chat_id, "✅ پاسخ ثبت شد. سؤال بعدی را می‌فرستم.")
        transaction.on_commit(lambda: send_next_follow_up(case))
        return True

    case = transition_case(case=case, target_status=Case.Status.FINALIZING, actor=user)
    state.active_case = case
    state.save(update_fields=["active_case", "updated_at"])
    latest_run = case.extraction_runs.select_related("schema").order_by("-created_at").first()
    schema = latest_run.schema if latest_run is not None else ensure_fire_loss_schema()
    start_extraction(case=case, schema=schema)
    send_text(
        provider,
        message.external_chat_id,
        "✅ همه پاسخ‌های تکمیلی ثبت شد.\n\n🔵 نویسه پرونده را دوباره با اطلاعات جدید تحلیل می‌کند.",
    )
    return True


@transaction.atomic
def handle_message(*, inbound: InboundUpdate, provider, user, message) -> None:
    state, _ = ConversationState.objects.select_for_update().get_or_create(
        user=user,
        provider=message.provider,
        external_chat_id=message.external_chat_id,
    )
    text = (message.text or "").strip()
    normalized_text = text.lower()

    if normalized_text == "/start":
        send_text(
            provider,
            message.external_chat_id,
            "👋 سلام، به نویسه خوش آمدید.\n\n"
            "نویسه اطلاعات پرونده را از متن، صوت، تصویر و مدارک شما جمع‌آوری می‌کند و در پایان یک گزارش تخصصی برای بررسی و تأیید آماده می‌کند.\n\n"
            "برای شروع، «➕ پرونده جدید» را انتخاب کنید.",
            main_menu_keyboard(),
        )
        return

    if normalized_text in STATUS_COMMANDS:
        if state.active_case is None:
            send_text(provider, message.external_chat_id, "📭 در حال حاضر پرونده فعالی ندارید.")
            return
        case = state.active_case
        messages = case.messages.count()
        voices = case.messages.filter(message_type=CaseMessage.MessageType.VOICE).count()
        images = case.messages.filter(message_type=CaseMessage.MessageType.IMAGE).count()
        documents = case.messages.filter(message_type=CaseMessage.MessageType.DOCUMENT).count()
        open_issues = case.field_issues.filter(status="open").count()
        report_revision = None
        if hasattr(case, "report") and case.report.current_revision_id:
            report_revision = case.report.current_revision.revision_number
        report_text = f"نسخه {report_revision}" if report_revision else "هنوز تولید نشده"
        send_text(
            provider,
            message.external_chat_id,
            "📁 وضعیت پرونده فعال\n"
            "━━━━━━━━━━━━━━\n"
            f"📝 عنوان: {case.title or 'بدون عنوان'}\n"
            f"🔖 کد پرونده: {case.case_code}\n\n"
            f"💬 پیام‌های ثبت‌شده: {messages}\n"
            f"🎙 پیام صوتی: {voices}\n"
            f"🖼 تصویر: {images}\n"
            f"📎 مدرک: {documents}\n"
            f"🧩 موارد نیازمند تکمیل: {open_issues}\n"
            f"📄 گزارش: {report_text}\n\n"
            f"{case_status_label(case.status)}\n"
            f"↳ {case_status_description(case.status)}",
        )
        return

    if normalized_text in APPROVE_COMMANDS:
        if state.active_case is None or state.active_case.status != Case.Status.READY_FOR_REVIEW:
            send_text(provider, message.external_chat_id, "ℹ️ گزارش آماده‌ای برای تأیید در پرونده فعال وجود ندارد.")
            return
        try:
            approve_report(case=state.active_case, user=user)
        except (ValueError, AttributeError):
            send_text(provider, message.external_chat_id, "⚠️ نسخه گزارش آماده تأیید پیدا نشد.")
            return
        state.active_case.refresh_from_db()
        send_text(
            provider,
            message.external_chat_id,
            f"✅ گزارش پرونده «{state.active_case.title or state.active_case.case_code}» با موفقیت تأیید شد.\n"
            f"وضعیت: {case_status_label(state.active_case.status)}",
        )
        return

    if normalized_text in ACTIVE_COMMANDS:
        if state.active_case is None:
            send_text(provider, message.external_chat_id, "📭 در حال حاضر پرونده فعالی ندارید.")
        else:
            send_text(
                provider,
                message.external_chat_id,
                "📁 پرونده فعال\n"
                f"📝 {state.active_case.title or 'بدون عنوان'}\n"
                f"🔖 کد: {state.active_case.case_code}\n"
                f"{case_status_label(state.active_case.status)}",
            )
        return

    if normalized_text.startswith("/active "):
        requested_code = text.split(maxsplit=1)[1].strip()
        selected = (
            Case.objects.filter(
                case_code__iexact=requested_code,
                tenant__memberships__user=user,
                tenant__memberships__is_active=True,
                status__in=[
                    Case.Status.DRAFT,
                    Case.Status.OPEN,
                    Case.Status.NEEDS_INFORMATION,
                    Case.Status.READY_FOR_REVIEW,
                ],
            )
            .distinct()
            .first()
        )
        if selected is None:
            send_text(provider, message.external_chat_id, "⚠️ پرونده قابل فعال‌سازی با این کد پیدا نشد.")
            return
        state.active_case = selected
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["active_case", "state", "pending_action", "updated_at"])
        send_text(
            provider,
            message.external_chat_id,
            "✅ پرونده فعال تغییر کرد.\n\n"
            f"📝 {selected.title or 'بدون عنوان'}\n"
            f"🔖 کد: {selected.case_code}\n"
            f"{case_status_label(selected.status)}",
        )
        if selected.status == Case.Status.NEEDS_INFORMATION:
            transaction.on_commit(lambda: send_next_follow_up(selected))
        return

    if normalized_text in CASES_COMMANDS:
        cases = list(
            Case.objects.filter(
                tenant__memberships__user=user,
                tenant__memberships__is_active=True,
                status__in=[
                    Case.Status.DRAFT,
                    Case.Status.OPEN,
                    Case.Status.FINALIZING,
                    Case.Status.NEEDS_INFORMATION,
                    Case.Status.READY_FOR_REVIEW,
                ],
            )
            .distinct()
            .order_by("-updated_at")[:10]
        )
        if not cases:
            send_text(provider, message.external_chat_id, "📭 پرونده بازی ندارید.")
            return
        lines = ["📂 پرونده‌های باز شما", "━━━━━━━━━━━━━━"]
        for item in cases:
            marker = "  ← پرونده فعال" if state.active_case_id == item.id else ""
            lines.append(
                f"• {item.title or 'بدون عنوان'}\n  🔖 {item.case_code}\n  {case_status_label(item.status)}{marker}"
            )
        lines.append("\nبرای انتخاب یک پرونده بنویسید:\n/active CASE_CODE")
        send_text(provider, message.external_chat_id, "\n\n".join(lines))
        return

    if _handle_follow_up_answer(
        state=state,
        inbound=inbound,
        provider=provider,
        user=user,
        message=message,
    ):
        return

    if state.state == "awaiting_case_title" and message.message_type == "text":
        title = "" if text == "بدون عنوان" else text
        case = create_case(user=user, tenant=_user_primary_tenant(user), title=title)
        state.active_case = case
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["active_case", "state", "pending_action", "updated_at"])
        send_text(
            provider,
            message.external_chat_id,
            "✅ پرونده با موفقیت ایجاد شد.\n\n"
            f"📝 عنوان: {case.title or 'بدون عنوان'}\n"
            f"🔖 کد پرونده: {case.case_code}\n"
            f"{case_status_label(case.status)}\n\n"
            "از حالا متن، صوت، تصویر و مدارکی که می‌فرستید به این پرونده اضافه می‌شوند.",
            main_menu_keyboard(),
        )
        return

    if normalized_text in NEW_CASE_COMMANDS:
        state.state = "awaiting_case_title"
        state.pending_action = {"action": "create_case"}
        state.save(update_fields=["state", "pending_action", "updated_at"])
        send_text(
            provider,
            message.external_chat_id,
            "📝 یک عنوان کوتاه برای پرونده بفرستید.\n\nاگر نمی‌خواهید عنوان وارد کنید، «بدون عنوان» را بفرستید.",
        )
        return

    if normalized_text in FINISH_COMMANDS:
        if state.active_case is None:
            send_text(provider, message.external_chat_id, "⚠️ پرونده فعالی برای پایان ورود اطلاعات وجود ندارد.")
            return
        try:
            state.active_case = finish_input(case=state.active_case, actor=user)
        except CaseTransitionError:
            send_text(provider, message.external_chat_id, "⚠️ این پرونده در وضعیت فعلی امکان پایان ورود اطلاعات ندارد.")
            return
        schema = ensure_fire_loss_schema()
        start_extraction(case=state.active_case, schema=schema)
        state.save(update_fields=["active_case", "updated_at"])
        send_text(
            provider,
            message.external_chat_id,
            "🔵 ورود اطلاعات پایان یافت.\n\nنویسه اکنون اطلاعات، صوت‌ها و مدارک پرونده را تحلیل می‌کند و کامل بودن اطلاعات را بررسی خواهد کرد.",
        )
        return

    stored = _record_message(inbound=inbound, user=user, state=state, message=message)
    _enqueue_attachment_if_present(stored=stored, message=message)
    if stored.assignment_status == CaseMessage.AssignmentStatus.ASSIGNED and stored.text.strip():
        sync_message_evidence(stored)

    if stored.assignment_status == CaseMessage.AssignmentStatus.UNASSIGNED:
        if state.active_case is None:
            send_text(
                provider,
                message.external_chat_id,
                "📭 در حال حاضر پرونده فعالی ندارید. پیام شما موقتاً نگهداری شد.\n\n"
                "«➕ پرونده جدید» را انتخاب کنید یا یکی از پرونده‌های باز را فعال کنید.",
                main_menu_keyboard(),
            )
        else:
            send_text(
                provider,
                message.external_chat_id,
                f"ℹ️ پرونده «{state.active_case.title or state.active_case.case_code}» اکنون در مرحله «{case_status_label(state.active_case.status, with_icon=False)}» است.\n"
                "این پیام بدون اتصال خودکار به پرونده نگهداری شد.",
            )
        return

    if message.file is not None:
        send_text(
            provider,
            message.external_chat_id,
            f"📎 فایل به پرونده «{stored.case.title or stored.case.case_code}» اضافه شد و برای پردازش امن در صف قرار گرفت.",
        )

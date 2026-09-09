from asgiref.sync import async_to_sync
from django.db import transaction

from apps.cases.models import Case
from apps.cases.services import CaseTransitionError, create_case, finish_input
from apps.processing.models import ProcessingJob
from apps.processing.services import ensure_attachment_job
from apps.processing.tasks import fetch_attachment
from apps.tenants.models import TenantMembership

from .models import CaseMessage, ConversationState, InboundUpdate


NEW_CASE_COMMANDS = {"/newcase", "پرونده جدید", "➕ پرونده جدید"}
CASES_COMMANDS = {"/cases", "پرونده‌های باز", "📂 پرونده‌های باز"}
ACTIVE_COMMANDS = {"/active", "پرونده فعال"}
STATUS_COMMANDS = {"/status", "وضعیت", "📊 وضعیت"}
FINISH_COMMANDS = {"/finish", "پایان ورود اطلاعات", "✅ پایان ورود اطلاعات"}


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
            "سلام، به نویسه خوش آمدید.\n\n"
            "نویسه اطلاعات پرونده را از متن، صوت و فایل جمع‌آوری می‌کند و در ادامه "
            "آن‌ها را به گزارش تخصصی تبدیل خواهد کرد.",
            main_menu_keyboard(),
        )
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
            f"پرونده ایجاد شد.\n\nعنوان: {case.title or 'بدون عنوان'}\n"
            f"کد: {case.case_code}\nوضعیت: باز و فعال\n\n"
            "از حالا پیام‌ها و فایل‌های عادی شما به این پرونده اضافه می‌شوند.",
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
            "یک عنوان کوتاه برای پرونده بفرستید. اگر نمی‌خواهید عنوان وارد کنید، «بدون عنوان» را بفرستید.",
        )
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
            send_text(provider, message.external_chat_id, "پرونده بازی ندارید.")
            return
        lines = ["پرونده‌های باز شما:"]
        for item in cases:
            marker = " ← فعال" if state.active_case_id == item.id else ""
            lines.append(f"• {item.title or 'بدون عنوان'} — {item.case_code}{marker}")
        lines.append("\nبرای فعال‌سازی یک پرونده بنویسید: /active CASE_CODE")
        send_text(provider, message.external_chat_id, "\n".join(lines))
        return

    if normalized_text.startswith("/active "):
        requested_code = text.split(maxsplit=1)[1].strip()
        selected = (
            Case.objects.filter(
                case_code__iexact=requested_code,
                tenant__memberships__user=user,
                tenant__memberships__is_active=True,
                status__in=[Case.Status.DRAFT, Case.Status.OPEN],
            )
            .distinct()
            .first()
        )
        if selected is None:
            send_text(
                provider,
                message.external_chat_id,
                "پرونده باز قابل فعال‌سازی با این کد پیدا نشد.",
            )
            return
        state.active_case = selected
        state.save(update_fields=["active_case", "updated_at"])
        send_text(
            provider,
            message.external_chat_id,
            f"پرونده فعال تغییر کرد:\n{selected.title or 'بدون عنوان'}\nکد: {selected.case_code}",
        )
        return

    if normalized_text in ACTIVE_COMMANDS:
        if state.active_case is None:
            send_text(provider, message.external_chat_id, "در حال حاضر پرونده فعالی ندارید.")
        else:
            send_text(
                provider,
                message.external_chat_id,
                f"پرونده فعال:\n{state.active_case.title or 'بدون عنوان'}\n"
                f"کد: {state.active_case.case_code}\nوضعیت: {state.active_case.status}",
            )
        return

    if normalized_text in STATUS_COMMANDS:
        if state.active_case is None:
            send_text(provider, message.external_chat_id, "در حال حاضر پرونده فعالی ندارید.")
            return
        case = state.active_case
        messages = case.messages.count()
        voices = case.messages.filter(message_type=CaseMessage.MessageType.VOICE).count()
        images = case.messages.filter(message_type=CaseMessage.MessageType.IMAGE).count()
        documents = case.messages.filter(message_type=CaseMessage.MessageType.DOCUMENT).count()
        send_text(
            provider,
            message.external_chat_id,
            f"پرونده فعال:\n{case.title or 'بدون عنوان'}\n\n"
            f"پیام‌های ثبت‌شده: {messages}\nصوت: {voices}\nتصویر: {images}\n"
            f"مدرک: {documents}\nوضعیت: {case.status}",
        )
        return

    if normalized_text in FINISH_COMMANDS:
        if state.active_case is None:
            send_text(provider, message.external_chat_id, "پرونده فعالی برای پایان ورود اطلاعات وجود ندارد.")
            return
        try:
            state.active_case = finish_input(case=state.active_case, actor=user)
        except CaseTransitionError:
            send_text(
                provider,
                message.external_chat_id,
                "این پرونده در وضعیت فعلی امکان پایان ورود اطلاعات ندارد.",
            )
            return
        state.save(update_fields=["active_case", "updated_at"])
        send_text(
            provider,
            message.external_chat_id,
            "ورود اطلاعات این پرونده پایان یافت و پرونده وارد مرحله بررسی نهایی شد.",
        )
        return

    stored = _record_message(inbound=inbound, user=user, state=state, message=message)
    _enqueue_attachment_if_present(stored=stored, message=message)

    if stored.assignment_status == CaseMessage.AssignmentStatus.UNASSIGNED:
        if state.active_case is None:
            send_text(
                provider,
                message.external_chat_id,
                "در حال حاضر پرونده فعالی ندارید. پیام شما موقتاً نگهداری شد.\n\n"
                "[➕ پرونده جدید] را انتخاب کنید یا یکی از پرونده‌های باز را فعال کنید.",
                main_menu_keyboard(),
            )
        else:
            send_text(
                provider,
                message.external_chat_id,
                f"ورود اطلاعات پرونده «{state.active_case.title or state.active_case.case_code}» پایان یافته است. "
                "این پیام موقتاً بدون پرونده نگهداری شد و خودکار به پرونده بسته اضافه نشد.",
            )
        return

    if message.file is not None:
        send_text(
            provider,
            message.external_chat_id,
            f"فایل به پرونده «{stored.case.title or stored.case.case_code}» اضافه شد و برای پردازش امن در صف قرار گرفت.",
        )

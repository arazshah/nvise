from asgiref.sync import async_to_sync
from django.db import transaction

from apps.cases.models import Case
from apps.cases.presentation import case_status_description, case_status_label
from apps.cases.services import (
    CaseTransitionError,
    archive_case,
    create_case,
    request_analysis,
    transition_case,
)
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


# Legacy commands remain supported for backwards compatibility, but they are no longer
# shown to end users. The primary UX is entirely button-driven.
NEW_CASE_COMMANDS = {"/newcase", "پرونده جدید", "➕ پرونده جدید"}
CASES_COMMANDS = {"/cases", "پرونده‌های من", "📂 پرونده‌های من", "پرونده‌های باز", "📂 پرونده‌های باز"}
ACTIVE_COMMANDS = {"/active", "پرونده فعال", "📁 پرونده فعال"}
STATUS_COMMANDS = {"/status", "وضعیت", "📊 وضعیت", "📊 وضعیت پرونده"}
ANALYZE_COMMANDS = {"/finish", "پایان ورود اطلاعات", "✅ پایان ورود اطلاعات", "🧠 تحلیل پرونده"}
APPROVE_COMMANDS = {"/approve", "تأیید گزارش", "✅ تأیید گزارش"}
ARCHIVE_COMMANDS = {"📦 بایگانی پرونده"}
CHANGE_CASE_COMMANDS = {"🔄 تغییر پرونده"}
BACK_TO_MENU_COMMANDS = {"↩️ بازگشت به منوی اصلی", "🏠 منوی اصلی"}


def send_text(provider, chat_id: str, text: str, keyboard: dict | None = None) -> None:
    if getattr(provider, "client", None) is None:
        return
    async_to_sync(provider.send_text)(chat_id, text, keyboard)


def main_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": "➕ پرونده جدید"}, {"text": "📂 پرونده‌های من"}],
            [{"text": "📁 پرونده فعال"}],
        ],
        "resize_keyboard": True,
    }


def active_case_keyboard(case: Case) -> dict:
    rows = [
        [{"text": "📊 وضعیت پرونده"}, {"text": "🧠 تحلیل پرونده"}],
        [{"text": "📂 پرونده‌های من"}, {"text": "🔄 تغییر پرونده"}],
    ]
    if case.status == Case.Status.READY_FOR_REVIEW:
        rows.append([{"text": "✅ تأیید گزارش"}])
    rows.extend(
        [
            [{"text": "📦 بایگانی پرونده"}],
            [{"text": "➕ پرونده جدید"}, {"text": "🏠 منوی اصلی"}],
        ]
    )
    return {"keyboard": rows, "resize_keyboard": True}


def _case_selection_keyboard(cases: list[Case]) -> tuple[dict, dict[str, str]]:
    mapping: dict[str, str] = {}
    rows: list[list[dict[str, str]]] = []
    for case in cases:
        title = (case.title or "بدون عنوان").strip()
        if len(title) > 28:
            title = f"{title[:25]}…"
        suffix = case.case_code[-6:]
        label = f"📁 {title} · {suffix}"
        mapping[label] = str(case.id)
        rows.append([{"text": label}])
    rows.append([{"text": "🏠 منوی اصلی"}])
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": True}, mapping


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
    can_assign = active_case is not None and active_case.lifecycle_status == Case.LifecycleStatus.ACTIVE
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


def _show_case_status(*, provider, chat_id: str, case: Case) -> None:
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
        chat_id,
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
        active_case_keyboard(case),
    )


def _show_case_picker(*, state: ConversationState, provider, user, chat_id: str) -> None:
    cases = list(
        Case.objects.filter(
            tenant__memberships__user=user,
            tenant__memberships__is_active=True,
            lifecycle_status=Case.LifecycleStatus.ACTIVE,
        )
        .distinct()
        .order_by("-updated_at")[:10]
    )
    if not cases:
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["state", "pending_action", "updated_at"])
        send_text(
            provider,
            chat_id,
            "📭 هنوز پرونده فعالی ندارید. برای شروع یک پرونده جدید بسازید.",
            main_menu_keyboard(),
        )
        return

    keyboard, mapping = _case_selection_keyboard(cases)
    state.state = "choosing_case"
    state.pending_action = {"action": "choose_case", "case_buttons": mapping}
    state.save(update_fields=["state", "pending_action", "updated_at"])
    send_text(
        provider,
        chat_id,
        "📂 پرونده‌های شما\n━━━━━━━━━━━━━━\n"
        "برای فعال‌کردن پرونده فقط روی نام آن بزنید. نیازی به نوشتن کد یا دستور نیست.",
        keyboard,
    )


def _handle_case_choice(*, state: ConversationState, provider, user, chat_id: str, text: str) -> bool:
    if state.state != "choosing_case":
        return False
    if text in BACK_TO_MENU_COMMANDS:
        state.active_case = None
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["active_case", "state", "pending_action", "updated_at"])
        send_text(provider, chat_id, "🏠 به منوی اصلی برگشتید.", main_menu_keyboard())
        return True

    mapping = state.pending_action.get("case_buttons") or {}
    case_id = mapping.get(text)
    if not case_id:
        send_text(provider, chat_id, "ℹ️ لطفاً یکی از پرونده‌های نمایش‌داده‌شده را با دکمه انتخاب کنید.")
        return True

    selected = (
        Case.objects.filter(
            pk=case_id,
            tenant__memberships__user=user,
            tenant__memberships__is_active=True,
            lifecycle_status=Case.LifecycleStatus.ACTIVE,
        )
        .distinct()
        .first()
    )
    if selected is None:
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["state", "pending_action", "updated_at"])
        send_text(provider, chat_id, "⚠️ این پرونده دیگر قابل انتخاب نیست.", main_menu_keyboard())
        return True

    state.active_case = selected
    state.state = "idle"
    state.pending_action = {}
    state.save(update_fields=["active_case", "state", "pending_action", "updated_at"])
    send_text(
        provider,
        chat_id,
        "✅ پرونده فعال شد.\n\n"
        f"📝 {selected.title or 'بدون عنوان'}\n"
        f"🔖 {selected.case_code}\n"
        f"{case_status_label(selected.status)}\n\n"
        "از اینجا خودتان انتخاب می‌کنید وضعیت پرونده را ببینید، تحلیل را ادامه دهید یا روی پرونده دیگری کار کنید.",
        active_case_keyboard(selected),
    )
    return True


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
        active_case_keyboard(case),
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
        keyboard = active_case_keyboard(state.active_case) if state.active_case else main_menu_keyboard()
        send_text(
            provider,
            message.external_chat_id,
            "👋 سلام، به نویسه خوش آمدید.\n\n"
            "اینجا نیازی به حفظ کردن دستور نیست. همه کارهای اصلی با دکمه‌های فارسی انجام می‌شود.\n\n"
            "می‌توانید پرونده بسازید، متن و صوت و مدرک بفرستید و هر زمان خواستید تحلیل را شروع کنید.",
            keyboard,
        )
        return

    if text in BACK_TO_MENU_COMMANDS:
        state.active_case = None
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["active_case", "state", "pending_action", "updated_at"])
        send_text(
            provider,
            message.external_chat_id,
            "🏠 منوی اصلی\n\n"
            "پرونده قبلی بسته یا حذف نشده است؛ فقط از آن خارج شدید. حالا می‌توانید پرونده جدید بسازید یا یکی از پرونده‌های قبلی را انتخاب کنید.",
            main_menu_keyboard(),
        )
        return

    if _handle_case_choice(
        state=state,
        provider=provider,
        user=user,
        chat_id=message.external_chat_id,
        text=text,
    ):
        return

    if normalized_text in NEW_CASE_COMMANDS:
        state.state = "awaiting_case_title"
        state.pending_action = {"action": "create_case"}
        state.save(update_fields=["state", "pending_action", "updated_at"])
        send_text(
            provider,
            message.external_chat_id,
            "📝 یک عنوان کوتاه برای پرونده بفرستید.\n\nمثلاً: «خسارت آتش‌سوزی فروشگاه»",
        )
        return

    if state.state == "awaiting_case_title" and message.message_type == CaseMessage.MessageType.TEXT:
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
            f"🔖 کد پرونده: {case.case_code}\n\n"
            "از حالا هر متن، صوت، تصویر یا مدرکی که بفرستید داخل همین پرونده نگهداری می‌شود.\n"
            "هر زمان آماده بودید، دکمه «🧠 تحلیل پرونده» را بزنید.",
            active_case_keyboard(case),
        )
        return

    if normalized_text in CASES_COMMANDS or normalized_text in CHANGE_CASE_COMMANDS:
        _show_case_picker(
            state=state,
            provider=provider,
            user=user,
            chat_id=message.external_chat_id,
        )
        return

    if normalized_text in ACTIVE_COMMANDS:
        if state.active_case is None:
            send_text(
                provider,
                message.external_chat_id,
                "📭 در حال حاضر پرونده فعالی ندارید.",
                main_menu_keyboard(),
            )
        else:
            _show_case_status(provider=provider, chat_id=message.external_chat_id, case=state.active_case)
        return

    if normalized_text in STATUS_COMMANDS:
        if state.active_case is None:
            send_text(provider, message.external_chat_id, "📭 در حال حاضر پرونده فعالی ندارید.", main_menu_keyboard())
            return
        _show_case_status(provider=provider, chat_id=message.external_chat_id, case=state.active_case)
        return

    if normalized_text in ANALYZE_COMMANDS:
        if state.active_case is None:
            send_text(provider, message.external_chat_id, "⚠️ ابتدا یک پرونده را فعال کنید.", main_menu_keyboard())
            return
        try:
            state.active_case = request_analysis(case=state.active_case, actor=user)
        except CaseTransitionError:
            send_text(
                provider,
                message.external_chat_id,
                "⚠️ این پرونده در وضعیت فعلی قابل تحلیل نیست.",
                active_case_keyboard(state.active_case),
            )
            return
        schema = ensure_fire_loss_schema()
        start_extraction(case=state.active_case, schema=schema)
        state.save(update_fields=["active_case", "updated_at"])
        send_text(
            provider,
            message.external_chat_id,
            "🧠 تحلیل پرونده شروع شد.\n\n"
            "نویسه متن‌ها، صوت‌ها و مدارک ثبت‌شده را بررسی می‌کند. نتیجه تحلیل و مواردی که نیاز به بررسی شما دارند از همین‌جا اعلام می‌شود.",
            active_case_keyboard(state.active_case),
        )
        return

    if normalized_text in ARCHIVE_COMMANDS:
        if state.active_case is None:
            send_text(provider, message.external_chat_id, "📭 پرونده فعالی برای بایگانی وجود ندارد.", main_menu_keyboard())
            return
        archived = archive_case(case=state.active_case, actor=user)
        state.active_case = None
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["active_case", "state", "pending_action", "updated_at"])
        send_text(
            provider,
            message.external_chat_id,
            "📦 پرونده بایگانی شد.\n\n"
            f"📝 {archived.title or 'بدون عنوان'}\n"
            "تمام اطلاعات و مدارک پرونده حفظ شده‌اند و می‌توانید بعداً از پنل وب آن را مشاهده یا بازگشایی کنید.",
            main_menu_keyboard(),
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
            f"✅ گزارش پرونده «{state.active_case.title or state.active_case.case_code}» با موفقیت تأیید شد.",
            active_case_keyboard(state.active_case),
        )
        return

    # Legacy /active CODE remains accepted for old clients but is intentionally undocumented.
    if normalized_text.startswith("/active "):
        requested_code = text.split(maxsplit=1)[1].strip()
        selected = (
            Case.objects.filter(
                case_code__iexact=requested_code,
                tenant__memberships__user=user,
                tenant__memberships__is_active=True,
                lifecycle_status=Case.LifecycleStatus.ACTIVE,
            )
            .distinct()
            .first()
        )
        if selected is not None:
            state.active_case = selected
            state.state = "idle"
            state.pending_action = {}
            state.save(update_fields=["active_case", "state", "pending_action", "updated_at"])
            send_text(provider, message.external_chat_id, "✅ پرونده فعال شد.", active_case_keyboard(selected))
        return

    if _handle_follow_up_answer(
        state=state,
        inbound=inbound,
        provider=provider,
        user=user,
        message=message,
    ):
        return

    stored = _record_message(inbound=inbound, user=user, state=state, message=message)
    _enqueue_attachment_if_present(stored=stored, message=message)
    if stored.assignment_status == CaseMessage.AssignmentStatus.ASSIGNED and stored.text.strip():
        sync_message_evidence(stored)

    if stored.assignment_status == CaseMessage.AssignmentStatus.UNASSIGNED:
        send_text(
            provider,
            message.external_chat_id,
            "📭 این پیام به پرونده‌ای متصل نشد. ابتدا از «📂 پرونده‌های من» یک پرونده را فعال کنید یا پرونده جدید بسازید.",
            main_menu_keyboard(),
        )
        return

    if message.file is not None:
        send_text(
            provider,
            message.external_chat_id,
            f"📎 فایل داخل پرونده «{stored.case.title or stored.case.case_code}» ذخیره شد و برای پردازش در صف قرار گرفت.",
            active_case_keyboard(stored.case),
        )
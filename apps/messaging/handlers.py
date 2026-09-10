from asgiref.sync import async_to_sync
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from apps.cases.actions import complete_case_action, next_best_action, sync_system_actions
from apps.cases.models import Case, CaseAction
from apps.cases.presentation import case_status_description, case_status_label
from apps.cases.reminders import snooze_action
from apps.cases.services import (
    CaseTransitionError,
    archive_case,
    create_case,
    request_analysis,
    transition_case,
)
from apps.evidence.services import sync_message_evidence
from apps.intelligence.catalog import ensure_schema_for_case
from apps.intelligence.followups import (
    next_pending_question,
    record_follow_up_answer,
    send_next_follow_up,
)
from apps.intelligence.professional_catalog import (
    case_types_for,
    find_case_type,
    profession_options,
    specialties_for,
)
from apps.intelligence.services import start_extraction
from apps.processing.models import ProcessingJob
from apps.processing.services import ensure_attachment_job
from apps.processing.tasks import fetch_attachment
from apps.reports.services import approve_report
from apps.tenants.models import TenantMembership

from .models import CaseMessage, ConversationState, InboundUpdate


NEW_CASE_COMMANDS = {"/newcase", "پرونده جدید", "➕ پرونده جدید"}
CASES_COMMANDS = {"/cases", "پرونده‌های من", "📂 پرونده‌های من", "پرونده‌های باز", "📂 پرونده‌های باز"}
ACTIVE_COMMANDS = {"/active", "پرونده فعال", "📁 پرونده فعال"}
STATUS_COMMANDS = {"/status", "وضعیت", "📊 وضعیت", "📊 وضعیت پرونده"}
ANALYZE_COMMANDS = {"/finish", "پایان ورود اطلاعات", "✅ پایان ورود اطلاعات", "🧠 تحلیل پرونده"}
APPROVE_COMMANDS = {"/approve", "تأیید گزارش", "✅ تأیید گزارش"}
ARCHIVE_COMMANDS = {"📦 بایگانی پرونده"}
CHANGE_CASE_COMMANDS = {"🔄 تغییر پرونده"}
PROFILE_COMMANDS = {"👤 پروفایل حرفه‌ای", "پروفایل حرفه‌ای"}
NEXT_ACTION_COMMANDS = {"📌 اقدام بعدی", "اقدام بعدی"}
REMINDER_DONE_COMMANDS = {"✅ انجام شد"}
REMINDER_SNOOZE_COMMANDS = {"⏰ فردا یادآوری کن"}
TODAY_COMMANDS = {"📋 کارهای امروز", "کارهای امروز"}
BACK_TO_MENU_COMMANDS = {"↩️ بازگشت به منوی اصلی", "🏠 منوی اصلی"}


def send_text(provider, chat_id: str, text: str, keyboard: dict | None = None) -> None:
    if getattr(provider, "client", None) is None:
        return
    async_to_sync(provider.send_text)(chat_id, text, keyboard)


def main_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": "➕ پرونده جدید"}, {"text": "📂 پرونده‌های من"}],
            [{"text": "📋 کارهای امروز"}, {"text": "📁 پرونده فعال"}],
            [{"text": "👤 پروفایل حرفه‌ای"}],
        ],
        "resize_keyboard": True,
    }


def active_case_keyboard(case: Case) -> dict:
    rows = [
        [{"text": "📊 وضعیت پرونده"}, {"text": "🧠 تحلیل پرونده"}],
        [{"text": "📌 اقدام بعدی"}, {"text": "📋 کارهای امروز"}],
        [{"text": "📂 پرونده‌های من"}, {"text": "🔄 تغییر پرونده"}],
        [{"text": "👤 پروفایل حرفه‌ای"}],
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


def _simple_choice_keyboard(labels: list[str]) -> dict:
    rows = [[{"text": label}] for label in labels]
    rows.append([{"text": "🏠 منوی اصلی"}])
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": True}


def _start_profession_flow(*, state, provider, chat_id: str) -> None:
    mapping = {f"👤 {label}": key for key, label in profession_options()}
    state.state = "choosing_profession"
    state.pending_action = {**(state.pending_action or {}), "profession_buttons": mapping}
    state.save(update_fields=["state", "pending_action", "updated_at"])
    send_text(
        provider,
        chat_id,
        "👤 پروفایل حرفه‌ای\n━━━━━━━━━━━━━━\nحرفه اصلی خود را انتخاب کنید. این انتخاب تعیین می‌کند نویسه پرونده‌ها را با چه نگاه تخصصی تحلیل کند.",
        _simple_choice_keyboard(list(mapping)),
    )


def _start_specialty_flow(*, state, provider, user, chat_id: str) -> None:
    options = specialties_for(user.profession_key)
    mapping = {f"🎯 {item.label}": item.key for item in options}
    state.state = "choosing_specialty"
    state.pending_action = {**(state.pending_action or {}), "specialty_buttons": mapping}
    state.save(update_fields=["state", "pending_action", "updated_at"])
    send_text(
        provider,
        chat_id,
        "🎯 تخصص\n━━━━━━━━━━━━━━\nحوزه‌ای را انتخاب کنید که بیشتر پرونده‌های شما در آن قرار می‌گیرند.",
        _simple_choice_keyboard(list(mapping)),
    )


def _start_case_type_flow(*, state, provider, user, chat_id: str) -> bool:
    case = state.active_case
    if case is None:
        return False
    options = case_types_for(user.profession_key, user.specialty_key)
    if not options:
        return False
    mapping = {f"📁 {item.label}": item.key for item in options}
    state.state = "choosing_case_type"
    state.pending_action = {**(state.pending_action or {}), "case_type_buttons": mapping}
    state.save(update_fields=["state", "pending_action", "updated_at"])
    send_text(
        provider,
        chat_id,
        "📁 نوع پرونده\n━━━━━━━━━━━━━━\nنوع این پرونده را انتخاب کنید تا نویسه روش تحلیل، پرسش‌های تخصصی و ساختار گزارش مناسب همین موضوع را به‌کار بگیرد.",
        _simple_choice_keyboard(list(mapping)),
    )
    return True


def _handle_professional_flow(*, state, provider, user, chat_id: str, text: str) -> bool:
    if state.state not in {"choosing_profession", "choosing_specialty", "choosing_case_type"}:
        return False
    if text in BACK_TO_MENU_COMMANDS:
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["state", "pending_action", "updated_at"])
        send_text(provider, chat_id, "🏠 به منوی اصلی برگشتید.", main_menu_keyboard())
        return True

    if state.state == "choosing_profession":
        key = (state.pending_action.get("profession_buttons") or {}).get(text)
        if not key:
            send_text(provider, chat_id, "ℹ️ لطفاً حرفه را با یکی از دکمه‌ها انتخاب کنید.")
            return True
        user.profession_key = key
        user.specialty_key = ""
        user.save(update_fields=["profession_key", "specialty_key", "updated_at"])
        _start_specialty_flow(state=state, provider=provider, user=user, chat_id=chat_id)
        return True

    if state.state == "choosing_specialty":
        key = (state.pending_action.get("specialty_buttons") or {}).get(text)
        valid = {item.key for item in specialties_for(user.profession_key)}
        if not key or key not in valid:
            send_text(provider, chat_id, "ℹ️ لطفاً تخصص را با یکی از دکمه‌ها انتخاب کنید.")
            return True
        user.specialty_key = key
        user.save(update_fields=["specialty_key", "updated_at"])
        if _start_case_type_flow(state=state, provider=provider, user=user, chat_id=chat_id):
            return True
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["state", "pending_action", "updated_at"])
        send_text(provider, chat_id, "✅ پروفایل حرفه‌ای شما ذخیره شد.", main_menu_keyboard())
        return True

    key = (state.pending_action.get("case_type_buttons") or {}).get(text)
    option = find_case_type(user.profession_key, user.specialty_key, key or "")
    if option is None or state.active_case is None:
        send_text(provider, chat_id, "ℹ️ لطفاً نوع پرونده را با یکی از دکمه‌ها انتخاب کنید.")
        return True
    case = state.active_case
    case.case_type_key = option.key
    case.vertical_key = option.vertical_key
    case.sub_vertical_key = option.sub_vertical_key
    case.save(update_fields=["case_type_key", "vertical_key", "sub_vertical_key", "updated_at"])
    state.state = "idle"
    state.pending_action = {}
    state.save(update_fields=["state", "pending_action", "updated_at"])
    send_text(
        provider,
        chat_id,
        f"✅ نوع پرونده ثبت شد: {option.label}\n\nاز این پس نویسه این پرونده را متناسب با حرفه، تخصص و موضوع آن بررسی می‌کند و پرسش‌ها و گزارش را بر همان اساس آماده می‌سازد.",
        active_case_keyboard(case),
    )
    return True



def _handle_reminder_action(*, state, provider, user, chat_id: str, text: str) -> bool:
    action_id = (state.pending_action or {}).get("reminder_action_id")
    if not action_id or text not in REMINDER_DONE_COMMANDS | REMINDER_SNOOZE_COMMANDS:
        return False
    action = CaseAction.objects.filter(
        pk=action_id,
        case__tenant__memberships__user=user,
        case__tenant__memberships__is_active=True,
    ).distinct().first()
    if action is None:
        pending = dict(state.pending_action or {})
        pending.pop("reminder_action_id", None)
        state.pending_action = pending
        state.save(update_fields=["pending_action", "updated_at"])
        send_text(provider, chat_id, "این یادآوری دیگر فعال نیست.")
        return True

    if text in REMINDER_DONE_COMMANDS:
        if action.system_key:
            send_text(
                provider,
                chat_id,
                "این اقدام با انجام مرحله مربوط به پرونده بسته می‌شود. پرونده را باز کنید و همان مرحله را انجام دهید.",
                active_case_keyboard(action.case),
            )
        else:
            complete_case_action(case=action.case, action_id=action.id, user=user)
            send_text(provider, chat_id, f"✅ «{action.title}» انجام‌شده ثبت شد.", active_case_keyboard(action.case))
    else:
        snooze_action(action=action, user=user, until=timezone.now() + timedelta(days=1))
        send_text(provider, chat_id, f"⏰ یادآوری «{action.title}» برای فردا تنظیم شد.", active_case_keyboard(action.case))

    state.active_case = action.case
    pending = dict(state.pending_action or {})
    pending.pop("reminder_action_id", None)
    state.pending_action = pending
    state.save(update_fields=["active_case", "pending_action", "updated_at"])
    return True


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
            "assignment_status": CaseMessage.AssignmentStatus.ASSIGNED if can_assign else CaseMessage.AssignmentStatus.UNASSIGNED,
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
    next_action = next_best_action(case)
    next_action_text = (
        f"\n\n📌 اقدام بعدی پیشنهادی: {next_action.title}\n↳ {next_action.description}"
        if next_action else
        "\n\n✅ در حال حاضر اقدام بازی برای این پرونده ثبت نشده است."
    )
    send_text(
        provider,
        chat_id,
        "📁 وضعیت پرونده فعال\n━━━━━━━━━━━━━━\n"
        f"📝 عنوان: {case.title or 'بدون عنوان'}\n"
        f"🔖 کد پرونده: {case.case_code}\n"
        f"🧭 نوع پرونده: {case.case_type_key or 'هنوز انتخاب نشده'}\n\n"
        f"💬 پیام‌های ثبت‌شده: {messages}\n🎙 پیام صوتی: {voices}\n🖼 تصویر: {images}\n📎 مدرک: {documents}\n"
        f"🧩 موارد نیازمند تکمیل: {open_issues}\n📄 گزارش: {report_text}\n\n"
        f"{case_status_label(case.status)}\n↳ {case_status_description(case.status)}"
        f"{next_action_text}",
        active_case_keyboard(case),
    )


def _show_case_picker(*, state: ConversationState, provider, user, chat_id: str) -> None:
    cases = list(
        Case.objects.filter(
            tenant__memberships__user=user,
            tenant__memberships__is_active=True,
            lifecycle_status=Case.LifecycleStatus.ACTIVE,
        ).distinct().order_by("-updated_at")[:10]
    )
    if not cases:
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["state", "pending_action", "updated_at"])
        send_text(provider, chat_id, "📭 هنوز پرونده فعالی ندارید. برای شروع یک پرونده جدید بسازید.", main_menu_keyboard())
        return
    keyboard, mapping = _case_selection_keyboard(cases)
    state.state = "choosing_case"
    state.pending_action = {"action": "choose_case", "case_buttons": mapping}
    state.save(update_fields=["state", "pending_action", "updated_at"])
    send_text(provider, chat_id, "📂 پرونده‌های شما\n━━━━━━━━━━━━━━\nبرای فعال‌کردن پرونده فقط روی نام آن بزنید.", keyboard)


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
    selected = Case.objects.filter(
        pk=case_id,
        tenant__memberships__user=user,
        tenant__memberships__is_active=True,
        lifecycle_status=Case.LifecycleStatus.ACTIVE,
    ).distinct().first()
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
    send_text(provider, chat_id, f"✅ پرونده فعال شد.\n\n📝 {selected.title or 'بدون عنوان'}\n🔖 {selected.case_code}", active_case_keyboard(selected))
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
        send_text(provider, message.external_chat_id, "✍️ برای پاسخ به سؤال تکمیلی، لطفاً پاسخ را فعلاً به‌صورت متن ارسال کنید.")
        return True
    question = record_follow_up_answer(state=state, inbound=inbound, user=user, message=message)
    case = question.case
    if next_pending_question(case) is not None:
        send_text(provider, message.external_chat_id, "✅ پاسخ ثبت شد. سؤال بعدی را می‌فرستم.")
        transaction.on_commit(lambda: send_next_follow_up(case))
        return True
    case = transition_case(case=case, target_status=Case.Status.FINALIZING, actor=user)
    state.active_case = case
    state.save(update_fields=["active_case", "updated_at"])
    latest_run = case.extraction_runs.select_related("schema").order_by("-created_at").first()
    schema = latest_run.schema if latest_run is not None else ensure_schema_for_case(case)
    start_extraction(case=case, schema=schema)
    send_text(provider, message.external_chat_id, "✅ همه پاسخ‌های تکمیلی ثبت شد.\n\n🔵 نویسه پرونده را دوباره با اطلاعات جدید تحلیل می‌کند.", active_case_keyboard(case))
    return True


@transaction.atomic
def handle_message(*, inbound: InboundUpdate, provider, user, message) -> None:
    state, _ = ConversationState.objects.select_for_update().get_or_create(
        user=user, provider=message.provider, external_chat_id=message.external_chat_id
    )
    text = (message.text or "").strip()
    normalized_text = text.lower()

    if normalized_text == "/start":
        keyboard = active_case_keyboard(state.active_case) if state.active_case else main_menu_keyboard()
        send_text(provider, message.external_chat_id, "👋 سلام، به نویسه خوش آمدید.\n\nهمه کارهای اصلی با دکمه‌های فارسی انجام می‌شود.", keyboard)
        return

    if text in BACK_TO_MENU_COMMANDS:
        state.active_case = None
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["active_case", "state", "pending_action", "updated_at"])
        send_text(provider, message.external_chat_id, "🏠 منوی اصلی\n\nپرونده قبلی بسته یا حذف نشده است؛ فقط از آن خارج شدید.", main_menu_keyboard())
        return

    if _handle_reminder_action(state=state, provider=provider, user=user, chat_id=message.external_chat_id, text=text):
        return

    if _handle_professional_flow(state=state, provider=provider, user=user, chat_id=message.external_chat_id, text=text):
        return

    if _handle_case_choice(state=state, provider=provider, user=user, chat_id=message.external_chat_id, text=text):
        return

    if text in PROFILE_COMMANDS:
        _start_profession_flow(state=state, provider=provider, chat_id=message.external_chat_id)
        return

    if normalized_text in NEW_CASE_COMMANDS:
        state.state = "awaiting_case_title"
        state.pending_action = {"action": "create_case"}
        state.save(update_fields=["state", "pending_action", "updated_at"])
        send_text(provider, message.external_chat_id, "📝 یک عنوان کوتاه برای پرونده بفرستید.")
        return

    if state.state == "awaiting_case_title" and message.message_type == CaseMessage.MessageType.TEXT:
        title = "" if text == "بدون عنوان" else text
        case = create_case(user=user, tenant=_user_primary_tenant(user), title=title)
        state.active_case = case
        state.pending_action = {"action": "configure_case"}
        state.save(update_fields=["active_case", "pending_action", "updated_at"])
        send_text(provider, message.external_chat_id, f"✅ پرونده ایجاد شد.\n📝 {case.title or 'بدون عنوان'}\n🔖 {case.case_code}")
        if not user.profession_key:
            _start_profession_flow(state=state, provider=provider, chat_id=message.external_chat_id)
        elif not user.specialty_key:
            _start_specialty_flow(state=state, provider=provider, user=user, chat_id=message.external_chat_id)
        elif not _start_case_type_flow(state=state, provider=provider, user=user, chat_id=message.external_chat_id):
            state.state = "idle"
            state.pending_action = {}
            state.save(update_fields=["state", "pending_action", "updated_at"])
            send_text(provider, message.external_chat_id, "پرونده آماده دریافت مدارک است.", active_case_keyboard(case))
        return

    if normalized_text in CASES_COMMANDS or normalized_text in CHANGE_CASE_COMMANDS:
        _show_case_picker(state=state, provider=provider, user=user, chat_id=message.external_chat_id)
        return

    if normalized_text in ACTIVE_COMMANDS:
        if state.active_case is None:
            send_text(provider, message.external_chat_id, "📭 در حال حاضر پرونده فعالی ندارید.", main_menu_keyboard())
        else:
            _show_case_status(provider=provider, chat_id=message.external_chat_id, case=state.active_case)
        return



    if text in TODAY_COMMANDS:
        active_cases = list(
            Case.objects.filter(
                tenant__memberships__user=user,
                tenant__memberships__is_active=True,
                lifecycle_status=Case.LifecycleStatus.ACTIVE,
            ).distinct().order_by("-updated_at")[:50]
        )
        for item in active_cases:
            sync_system_actions(item)
        actions = list(
            CaseAction.objects.filter(
                case__tenant__memberships__user=user,
                case__tenant__memberships__is_active=True,
                status=CaseAction.Status.OPEN,
            ).select_related("case").distinct().order_by("-priority", "due_at", "created_at")[:8]
        )
        if not actions:
            send_text(provider, message.external_chat_id, "✅ در حال حاضر کار بازی برای پیگیری ندارید.", main_menu_keyboard())
            return
        lines = ["📋 کارهای امروز", "━━━━━━━━━━━━━━"]
        for action in actions:
            lines.append(f"• {action.case.title or action.case.case_code}: {action.title}")
        send_text(provider, message.external_chat_id, "\n".join(lines), main_menu_keyboard())
        return

    if text in NEXT_ACTION_COMMANDS:
        if state.active_case is None:
            send_text(provider, message.external_chat_id, "📭 ابتدا یک پرونده را فعال کنید.", main_menu_keyboard())
            return
        action = next_best_action(state.active_case)
        if action is None:
            send_text(provider, message.external_chat_id, "✅ در حال حاضر اقدام بازی برای این پرونده وجود ندارد.", active_case_keyboard(state.active_case))
            return
        send_text(
            provider,
            message.external_chat_id,
            f"📌 اقدام بعدی پیشنهادی\n━━━━━━━━━━━━━━\n{action.title}\n\n{action.description}",
            active_case_keyboard(state.active_case),
        )
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
        if not user.profession_key or not user.specialty_key or not state.active_case.case_type_key:
            send_text(provider, message.external_chat_id, "👤 قبل از تحلیل، حرفه، تخصص و نوع پرونده را مشخص کنید.")
            if not user.profession_key:
                _start_profession_flow(state=state, provider=provider, chat_id=message.external_chat_id)
            elif not user.specialty_key:
                _start_specialty_flow(state=state, provider=provider, user=user, chat_id=message.external_chat_id)
            else:
                _start_case_type_flow(state=state, provider=provider, user=user, chat_id=message.external_chat_id)
            return
        try:
            state.active_case = request_analysis(case=state.active_case, actor=user)
        except CaseTransitionError:
            send_text(provider, message.external_chat_id, "⚠️ این پرونده در وضعیت فعلی قابل تحلیل نیست.", active_case_keyboard(state.active_case))
            return
        schema = ensure_schema_for_case(state.active_case)
        start_extraction(case=state.active_case, schema=schema)
        state.save(update_fields=["active_case", "updated_at"])
        send_text(provider, message.external_chat_id, "🧠 تحلیل پرونده شروع شد.\n\nنویسه پرونده را بر اساس حرفه، تخصص و نوع پرونده انتخاب‌شده بررسی می‌کند.", active_case_keyboard(state.active_case))
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
        send_text(provider, message.external_chat_id, f"📦 پرونده بایگانی شد.\n\n📝 {archived.title or 'بدون عنوان'}", main_menu_keyboard())
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
        send_text(provider, message.external_chat_id, f"✅ گزارش پرونده «{state.active_case.title or state.active_case.case_code}» با موفقیت تأیید شد.", active_case_keyboard(state.active_case))
        return

    if normalized_text.startswith("/active "):
        requested_code = text.split(maxsplit=1)[1].strip()
        selected = Case.objects.filter(
            case_code__iexact=requested_code,
            tenant__memberships__user=user,
            tenant__memberships__is_active=True,
            lifecycle_status=Case.LifecycleStatus.ACTIVE,
        ).distinct().first()
        if selected is not None:
            state.active_case = selected
            state.state = "idle"
            state.pending_action = {}
            state.save(update_fields=["active_case", "state", "pending_action", "updated_at"])
            send_text(provider, message.external_chat_id, "✅ پرونده فعال شد.", active_case_keyboard(selected))
        return

    if _handle_follow_up_answer(state=state, inbound=inbound, provider=provider, user=user, message=message):
        return

    stored = _record_message(inbound=inbound, user=user, state=state, message=message)
    _enqueue_attachment_if_present(stored=stored, message=message)
    if stored.assignment_status == CaseMessage.AssignmentStatus.ASSIGNED and stored.text.strip():
        sync_message_evidence(stored)
    if stored.assignment_status == CaseMessage.AssignmentStatus.UNASSIGNED:
        send_text(provider, message.external_chat_id, "📭 این پیام به پرونده‌ای متصل نشد. ابتدا یک پرونده را فعال کنید یا پرونده جدید بسازید.", main_menu_keyboard())
        return
    if message.file is not None:
        send_text(provider, message.external_chat_id, f"📎 فایل داخل پرونده «{stored.case.title or stored.case.case_code}» ذخیره شد و برای پردازش در صف قرار گرفت.", active_case_keyboard(stored.case))

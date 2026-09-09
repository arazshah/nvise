from asgiref.sync import async_to_sync
from django.db import transaction

from apps.messaging.models import ConversationState
from apps.portal.tasks import send_review_link
from apps.reports.services import generate_report_revision

from .followups import ensure_follow_up_questions, send_next_follow_up
from .results import (
    ADD_EVIDENCE_LABEL,
    CONTINUE_CURRENT_LABEL,
    GENERATE_REPORT_LABEL,
    RESOLVE_ISSUES_LABEL,
    analysis_result_keyboard,
    waive_open_issues,
)


ANALYSIS_ACTION_LABELS = {
    RESOLVE_ISSUES_LABEL,
    ADD_EVIDENCE_LABEL,
    CONTINUE_CURRENT_LABEL,
    GENERATE_REPORT_LABEL,
}


def handle_analysis_action(*, provider, user, message) -> bool:
    text = (message.text or "").strip()
    if text not in ANALYSIS_ACTION_LABELS:
        return False

    state = (
        ConversationState.objects.select_related("active_case")
        .filter(
            user=user,
            provider=message.provider,
            external_chat_id=message.external_chat_id,
        )
        .first()
    )
    if state is None or state.active_case is None:
        return False

    case = state.active_case

    if text == RESOLVE_ISSUES_LABEL:
        questions = ensure_follow_up_questions(case)
        if not questions:
            async_to_sync(provider.send_text)(
                message.external_chat_id,
                "✅ مورد حل‌نشده‌ای برای این تحلیل باقی نمانده است.\n\n"
                "اگر آماده هستید می‌توانید گزارش را تولید کنید.",
                analysis_result_keyboard(case),
            )
            return True
        transaction.on_commit(lambda: send_next_follow_up(case))
        return True

    if text == ADD_EVIDENCE_LABEL:
        state.state = "idle"
        state.pending_action = {"analysis_result_case_id": str(case.id)}
        state.save(update_fields=["state", "pending_action", "updated_at"])
        async_to_sync(provider.send_text)(
            message.external_chat_id,
            "📎 اطلاعات یا مدرک بیشتری اضافه کنید.\n\n"
            "می‌توانید متن، صوت، تصویر یا فایل بفرستید. همه موارد داخل همین پرونده ذخیره می‌شوند.\n"
            "پس از افزودن اطلاعات جدید، دوباره دکمه «🧠 تحلیل پرونده» را بزنید.",
        )
        return True

    if text == CONTINUE_CURRENT_LABEL:
        waive_open_issues(case, actor=user)
        case.refresh_from_db()
        state.state = "idle"
        state.pending_action = {"analysis_result_case_id": str(case.id)}
        state.save(update_fields=["state", "pending_action", "updated_at"])
        async_to_sync(provider.send_text)(
            message.external_chat_id,
            "✅ موارد حل‌نشده با انتخاب شما بسته شدند.\n\n"
            "نویسه می‌تواند گزارش را با همین اطلاعات موجود تولید کند.",
            analysis_result_keyboard(case),
        )
        return True

    if text == GENERATE_REPORT_LABEL:
        try:
            generate_report_revision(case=case, created_by=user)
        except ValueError:
            async_to_sync(provider.send_text)(
                message.external_chat_id,
                "⚠️ هنوز امکان تولید گزارش وجود ندارد.\n\n"
                "تحلیل پرونده باید کامل شده باشد و هیچ مورد بازی بدون تصمیم شما باقی نماند.\n"
                "ابتدا موارد را رفع کنید یا گزینه «ادامه با اطلاعات فعلی» را انتخاب کنید.",
                analysis_result_keyboard(case),
            )
            return True
        case.refresh_from_db()
        state.active_case = case
        state.state = "idle"
        state.pending_action = {}
        state.save(update_fields=["active_case", "state", "pending_action", "updated_at"])
        async_to_sync(provider.send_text)(
            message.external_chat_id,
            "📄 گزارش بر اساس اطلاعات فعلی پرونده تولید شد.\n\n"
            "لینک امن بررسی گزارش برای شما ارسال می‌شود.",
        )
        transaction.on_commit(lambda: send_review_link.delay(str(case.id)))
        return True

    return False

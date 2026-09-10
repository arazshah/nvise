from __future__ import annotations

from datetime import datetime, timedelta

from asgiref.sync import async_to_sync
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import BaleIdentity
from apps.messaging.models import ConversationState
from apps.messaging.providers.bale import BaleProvider
from apps.system.integrations import get_bale_config

from .models import CaseAction, CaseReminder, ReminderPreference


def get_preferences(user) -> ReminderPreference:
    prefs, _ = ReminderPreference.objects.get_or_create(user=user)
    return prefs


def _in_quiet_hours(now_local, prefs: ReminderPreference) -> bool:
    current = now_local.time().replace(tzinfo=None)
    start = prefs.quiet_start
    end = prefs.quiet_end
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def next_allowed_time(now, prefs: ReminderPreference):
    local_now = timezone.localtime(now)
    if not _in_quiet_hours(local_now, prefs):
        return now
    end = prefs.quiet_end
    target_date = local_now.date()
    if prefs.quiet_start > prefs.quiet_end and local_now.time().replace(tzinfo=None) >= prefs.quiet_start:
        target_date += timedelta(days=1)
    local_target = datetime.combine(target_date, end)
    return timezone.make_aware(local_target, timezone.get_current_timezone())


def ensure_action_reminder(action: CaseAction, *, user=None, remind_at=None) -> CaseReminder | None:
    if action.status != CaseAction.Status.OPEN:
        return None
    user = user or action.created_by or action.case.created_by
    prefs = get_preferences(user)
    if not prefs.reminders_enabled:
        return None
    when = remind_at or action.due_at
    if when is None:
        return None
    dedupe_key = f"action:{action.id}:{when.isoformat()}"
    reminder, _ = CaseReminder.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "action": action,
            "user": user,
            "remind_at": when,
        },
    )
    return reminder


def schedule_report_review_reminder(action: CaseAction) -> CaseReminder | None:
    if action.action_type != CaseAction.ActionType.REVIEW_REPORT:
        return None
    user = action.case.created_by
    prefs = get_preferences(user)
    if not prefs.reminders_enabled or not prefs.report_review_enabled:
        return None
    when = timezone.now() + timedelta(hours=48)
    dedupe_key = f"report-review:{action.id}"
    reminder, _ = CaseReminder.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "action": action,
            "user": user,
            "remind_at": when,
        },
    )
    return reminder


def cancel_action_reminders(action: CaseAction) -> None:
    CaseReminder.objects.filter(
        action=action,
        status__in=[CaseReminder.Status.PENDING, CaseReminder.Status.DISPATCHING],
    ).update(status=CaseReminder.Status.CANCELLED)


def _reminder_keyboard(action: CaseAction) -> dict:
    return {
        "keyboard": [
            [{"text": "✅ انجام شد"}, {"text": "⏰ فردا یادآوری کن"}],
            [{"text": "📁 پرونده فعال"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def reminder_text(reminder: CaseReminder) -> str:
    action = reminder.action
    case = action.case
    lines = [
        "⏰ یادآوری نویسه",
        "━━━━━━━━━━━━━━",
        f"📁 {case.title or case.case_code}",
        f"📌 {action.title}",
    ]
    if action.description:
        lines.extend(["", action.description])
    return "\n".join(lines)


def deliver_reminder(reminder: CaseReminder) -> None:
    identity = BaleIdentity.objects.filter(user=reminder.user, is_active=True).first()
    if identity is None:
        raise RuntimeError("برای این کاربر حساب بله فعالی پیدا نشد.")
    config = get_bale_config()
    if not config.enabled or not config.bot_token:
        raise RuntimeError("ارسال پیام بله فعال نیست.")
    provider = BaleProvider(config.bot_token)
    async_to_sync(provider.send_text)(
        identity.external_chat_id,
        reminder_text(reminder),
        _reminder_keyboard(reminder.action),
    )
    state, _ = ConversationState.objects.get_or_create(
        user=reminder.user,
        provider="bale",
        external_chat_id=identity.external_chat_id,
    )
    pending = dict(state.pending_action or {})
    pending["reminder_action_id"] = str(reminder.action_id)
    state.pending_action = pending
    state.save(update_fields=["pending_action", "updated_at"])


@transaction.atomic
def claim_due_reminders(limit: int = 50) -> list[CaseReminder]:
    now = timezone.now()
    rows = list(
        CaseReminder.objects.select_for_update(skip_locked=True)
        .filter(status=CaseReminder.Status.PENDING, remind_at__lte=now)
        .select_related("action__case", "user")
        .order_by("remind_at")[:limit]
    )
    claimed = []
    for row in rows:
        prefs = get_preferences(row.user)
        if not prefs.reminders_enabled:
            row.status = CaseReminder.Status.CANCELLED
            row.save(update_fields=["status", "updated_at"])
            continue
        allowed_at = next_allowed_time(now, prefs)
        if allowed_at > now:
            row.remind_at = allowed_at
            row.save(update_fields=["remind_at", "updated_at"])
            continue
        if row.action.status != CaseAction.Status.OPEN:
            row.status = CaseReminder.Status.CANCELLED
            row.save(update_fields=["status", "updated_at"])
            continue
        row.status = CaseReminder.Status.DISPATCHING
        row.attempts += 1
        row.last_error = ""
        row.save(update_fields=["status", "attempts", "last_error", "updated_at"])
        claimed.append(row)
    return claimed


def mark_reminder_sent(reminder_id) -> None:
    CaseReminder.objects.filter(pk=reminder_id).update(
        status=CaseReminder.Status.SENT,
        sent_at=timezone.now(),
        last_error="",
    )


def mark_reminder_failed(reminder_id, error: Exception) -> None:
    CaseReminder.objects.filter(pk=reminder_id).update(
        status=CaseReminder.Status.PENDING,
        remind_at=timezone.now() + timedelta(minutes=15),
        last_error=str(error)[:2000],
    )


def snooze_action(*, action: CaseAction, user, until) -> CaseReminder:
    CaseReminder.objects.filter(
        action=action,
        user=user,
        status__in=[CaseReminder.Status.PENDING, CaseReminder.Status.DISPATCHING],
    ).update(status=CaseReminder.Status.CANCELLED)
    return ensure_action_reminder(action, user=user, remind_at=until)

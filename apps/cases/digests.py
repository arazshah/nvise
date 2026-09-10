from __future__ import annotations

from datetime import timedelta

from asgiref.sync import async_to_sync
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import BaleIdentity
from apps.messaging.providers.bale import BaleProvider
from apps.system.integrations import get_bale_config

from .actions import sync_system_actions
from .models import Case, CaseAction, DigestDelivery, ReminderPreference
from .reminders import _in_quiet_hours, get_preferences


def _sync_user_cases(user) -> None:
    cases = (
        Case.objects.filter(
            tenant__memberships__user=user,
            tenant__memberships__is_active=True,
            lifecycle_status=Case.LifecycleStatus.ACTIVE,
        )
        .distinct()
        .order_by("-updated_at")[:200]
    )
    for case in cases:
        sync_system_actions(case)


def _provider_for_user(user):
    identity = BaleIdentity.objects.filter(user=user, is_active=True).first()
    if identity is None:
        return None, None
    config = get_bale_config()
    if not config.enabled or not config.bot_token:
        return None, None
    return BaleProvider(config.bot_token), identity.external_chat_id


def _send(user, text: str, keyboard: dict | None = None) -> bool:
    provider, chat_id = _provider_for_user(user)
    if provider is None:
        return False
    async_to_sync(provider.send_text)(chat_id, text, keyboard)
    return True


def daily_digest_text(user) -> tuple[str, int]:
    _sync_user_cases(user)
    now = timezone.now()
    end = now + timedelta(hours=24)
    actions = (
        CaseAction.objects.filter(
            case__tenant__memberships__user=user,
            case__tenant__memberships__is_active=True,
            case__lifecycle_status=Case.LifecycleStatus.ACTIVE,
            status=CaseAction.Status.OPEN,
        )
        .filter(Q(due_at__lte=end) | Q(priority__gte=CaseAction.Priority.HIGH))
        .select_related("case")
        .distinct()
        .order_by("-priority", "due_at")[:10]
    )
    rows = list(actions)
    if not rows:
        return "", 0
    overdue = sum(1 for row in rows if row.due_at and row.due_at < now)
    lines = ["☀️ مرور کاری امروز", "━━━━━━━━━━━━━━"]
    if overdue:
        lines.append(f"⏰ {overdue} کار عقب‌افتاده")
    lines.append(f"📋 {len(rows)} کار نیازمند توجه")
    lines.append("")
    for row in rows[:6]:
        lines.append(f"• {row.case.title or row.case.case_code}: {row.title}")
    if len(rows) > 6:
        lines.append(f"… و {len(rows) - 6} مورد دیگر")
    return "\n".join(lines), len(rows)


def weekly_digest_text(user) -> tuple[str, int]:
    _sync_user_cases(user)
    now = timezone.now()
    actions = CaseAction.objects.filter(
        case__tenant__memberships__user=user,
        case__tenant__memberships__is_active=True,
        case__lifecycle_status=Case.LifecycleStatus.ACTIVE,
        status=CaseAction.Status.OPEN,
    ).distinct()
    open_count = actions.count()
    overdue_count = actions.filter(due_at__lt=now).count()
    report_count = Case.objects.filter(
        tenant__memberships__user=user,
        tenant__memberships__is_active=True,
        report_status=Case.ReportStatus.READY_FOR_REVIEW,
    ).distinct().count()
    prefs = get_preferences(user)
    stale_count = (
        actions.filter(action_type=CaseAction.ActionType.STALE_CASE).count()
        if prefs.stale_case_enabled
        else 0
    )
    if not any([open_count, overdue_count, report_count, stale_count]):
        return "", 0
    lines = [
        "📊 مرور هفتگی نویسه",
        "━━━━━━━━━━━━━━",
        f"📋 کارهای باز: {open_count}",
        f"⏰ عقب‌افتاده: {overdue_count}",
        f"📄 گزارش آماده بررسی: {report_count}",
        f"📁 پرونده بدون اقدام: {stale_count}",
        "",
        "موارد مهم را در «کارهای امروز» می‌توانید یکجا ببینید.",
    ]
    return "\n".join(lines), open_count + report_count + stale_count


def send_digest_for_user(user, digest_type: str) -> bool:
    prefs = get_preferences(user)
    enabled = (
        prefs.daily_digest_enabled
        if digest_type == DigestDelivery.DigestType.DAILY
        else prefs.weekly_digest_enabled
    )
    if not prefs.reminders_enabled or not enabled:
        return False
    if _in_quiet_hours(timezone.localtime(), prefs):
        return False

    today = timezone.localdate()
    if digest_type == DigestDelivery.DigestType.DAILY:
        period_key = today.isoformat()
        text, count = daily_digest_text(user)
    else:
        iso = today.isocalendar()
        period_key = f"{iso.year}-W{iso.week:02d}"
        text, count = weekly_digest_text(user)
    if not text or count == 0:
        return False
    if DigestDelivery.objects.filter(
        user=user,
        digest_type=digest_type,
        period_key=period_key,
    ).exists():
        return False

    keyboard = {
        "keyboard": [[{"text": "📋 کارهای امروز"}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }
    if not _send(user, text, keyboard):
        return False
    DigestDelivery.objects.create(
        user=user,
        digest_type=digest_type,
        period_key=period_key,
        item_count=count,
    )
    return True


def send_enabled_digests(digest_type: str) -> dict:
    field = "daily_digest_enabled" if digest_type == DigestDelivery.DigestType.DAILY else "weekly_digest_enabled"
    prefs = ReminderPreference.objects.filter(
        reminders_enabled=True,
        **{field: True},
    ).select_related("user")
    sent = 0
    for pref in prefs:
        if send_digest_for_user(pref.user, digest_type):
            sent += 1
    return {"eligible": prefs.count(), "sent": sent}

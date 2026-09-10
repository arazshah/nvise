from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.intelligence.models import CaseFieldIssue

from .models import Case, CaseAction, CaseEvent


@dataclass(frozen=True)
class NextBestAction:
    action_id: str | None
    title: str
    description: str
    action_type: str
    priority: int
    due_at: object | None
    route_name: str | None


_SYSTEM_ACTIONS = {
    "analysis:start": {
        "title": "تحلیل پرونده را شروع کنید",
        "description": "اطلاعات و مدارک ثبت‌شده آماده‌اند تا نویسه آن‌ها را بررسی کند.",
        "action_type": CaseAction.ActionType.START_ANALYSIS,
        "priority": CaseAction.Priority.NORMAL,
        "route_name": "portal:analysis-overview",
    },
    "analysis:review": {
        "title": "موارد نیازمند بررسی را مشخص کنید",
        "description": "تحلیل انجام شده و بعضی موارد به تصمیم یا نظر تخصصی شما نیاز دارند.",
        "action_type": CaseAction.ActionType.REVIEW_ANALYSIS,
        "priority": CaseAction.Priority.HIGH,
        "route_name": "portal:analysis-overview",
    },
    "analysis:retry": {
        "title": "تحلیل ناموفق را دوباره بررسی کنید",
        "description": "آخرین تحلیل کامل نشده است. وضعیت پرونده را بررسی و تحلیل را دوباره اجرا کنید.",
        "action_type": CaseAction.ActionType.RETRY_ANALYSIS,
        "priority": CaseAction.Priority.HIGH,
        "route_name": "portal:analysis-overview",
    },
    "report:generate": {
        "title": "گزارش تخصصی را تولید کنید",
        "description": "تحلیل کامل است و مورد حل‌نشده‌ای باقی نمانده؛ پرونده برای تهیه گزارش آماده است.",
        "action_type": CaseAction.ActionType.GENERATE_REPORT,
        "priority": CaseAction.Priority.HIGH,
        "route_name": "portal:analysis-overview",
    },
    "report:review": {
        "title": "گزارش آماده را بررسی کنید",
        "description": "نسخه جدید گزارش آماده بررسی کارشناسی و تأیید منبع‌ها و ادعاهای مهم است.",
        "action_type": CaseAction.ActionType.REVIEW_REPORT,
        "priority": CaseAction.Priority.HIGH,
        "route_name": "portal:case-review",
    },
    "report:regenerate": {
        "title": "گزارش را با اصلاحات جدید بازسازی کنید",
        "description": "داده‌های پرونده پس از آخرین نسخه گزارش تغییر کرده‌اند و لازم است گزارش تازه ساخته شود.",
        "action_type": CaseAction.ActionType.REGENERATE_REPORT,
        "priority": CaseAction.Priority.URGENT,
        "route_name": "portal:grounding-overview",
    },
    "case:stale": {
        "title": "این پرونده مدتی بدون اقدام مانده است",
        "description": "پرونده هنوز فعال است اما بیش از یک هفته تغییری نداشته؛ بررسی کنید آیا پیگیری، تکمیل یا بایگانی لازم است.",
        "action_type": CaseAction.ActionType.STALE_CASE,
        "priority": CaseAction.Priority.LOW,
        "route_name": "portal:case-repository",
    },
}


def _wanted_system_keys(case: Case) -> list[str]:
    if case.lifecycle_status != Case.LifecycleStatus.ACTIVE:
        return []

    if case.report_status == Case.ReportStatus.DRAFT and hasattr(case, "report") and case.report.current_revision_id:
        return ["report:regenerate"]

    if case.report_status == Case.ReportStatus.READY_FOR_REVIEW:
        return ["report:review"]

    if case.analysis_status == Case.AnalysisStatus.FAILED:
        return ["analysis:retry"]

    if case.analysis_status == Case.AnalysisStatus.NEEDS_REVIEW:
        return ["analysis:review"]

    if case.analysis_status == Case.AnalysisStatus.COMPLETED:
        has_open_issues = CaseFieldIssue.objects.filter(
            case=case,
            status=CaseFieldIssue.Status.OPEN,
        ).exists()
        if not has_open_issues and case.report_status == Case.ReportStatus.NOT_CREATED:
            return ["report:generate"]
        return []

    if case.analysis_status == Case.AnalysisStatus.NOT_STARTED and case.messages.exists():
        return ["analysis:start"]

    if (
        case.report_status != Case.ReportStatus.APPROVED
        and case.messages.exists()
        and case.updated_at <= timezone.now() - timedelta(days=7)
    ):
        return ["case:stale"]

    return []


@transaction.atomic
def sync_system_actions(case: Case) -> list[CaseAction]:
    # Lock only the Case row. The reverse report relation is optional and
    # selecting it here would make PostgreSQL apply FOR UPDATE to a nullable
    # outer join.
    locked_case = Case.objects.select_for_update().get(pk=case.pk)
    wanted = _wanted_system_keys(locked_case)
    existing = {
        row.system_key: row
        for row in CaseAction.objects.select_for_update().filter(
            case=locked_case,
            system_key__in=list(_SYSTEM_ACTIONS),
        )
    }

    now = timezone.now()
    active_rows = []
    for key, row in existing.items():
        if key not in wanted and row.status == CaseAction.Status.OPEN:
            row.status = CaseAction.Status.DONE
            row.completed_at = now
            row.save(update_fields=["status", "completed_at", "updated_at"])
            from .reminders import cancel_action_reminders
            cancel_action_reminders(row)

    for key in wanted:
        config = _SYSTEM_ACTIONS[key]
        row = existing.get(key)
        if row is None:
            row = CaseAction.objects.create(
                case=locked_case,
                title=config["title"],
                description=config["description"],
                action_type=config["action_type"],
                priority=config["priority"],
                system_key=key,
                source_event="case.workflow",
                metadata={"route_name": config["route_name"]},
            )
            CaseEvent.objects.create(
                case=locked_case,
                event_type="case.action_created",
                payload={"action_id": str(row.id), "system_key": key},
            )
        else:
            changed = False
            if row.status != CaseAction.Status.OPEN:
                row.status = CaseAction.Status.OPEN
                row.completed_at = None
                changed = True
            for field in ("title", "description", "action_type", "priority"):
                value = config[field]
                if getattr(row, field) != value:
                    setattr(row, field, value)
                    changed = True
            metadata = {"route_name": config["route_name"]}
            if row.metadata != metadata:
                row.metadata = metadata
                changed = True
            if changed:
                row.save(
                    update_fields=[
                        "status",
                        "completed_at",
                        "title",
                        "description",
                        "action_type",
                        "priority",
                        "metadata",
                        "updated_at",
                    ]
                )
        if row.action_type == CaseAction.ActionType.REVIEW_REPORT:
            from .reminders import schedule_report_review_reminder
            schedule_report_review_reminder(row)
        active_rows.append(row)
    return active_rows


def open_case_actions(case: Case):
    sync_system_actions(case)
    return CaseAction.objects.filter(case=case, status=CaseAction.Status.OPEN).order_by(
        "-priority", "due_at", "created_at"
    )


def next_best_action(case: Case) -> NextBestAction | None:
    row = open_case_actions(case).first()
    if row is None:
        return None
    return NextBestAction(
        action_id=str(row.id),
        title=row.title,
        description=row.description,
        action_type=row.action_type,
        priority=row.priority,
        due_at=row.due_at,
        route_name=(row.metadata or {}).get("route_name"),
    )


@transaction.atomic
def create_manual_action(*, case: Case, user, title: str, description: str = "", due_at=None) -> CaseAction:
    title = title.strip()
    if not title:
        raise ValueError("عنوان اقدام نمی‌تواند خالی باشد.")
    if case.lifecycle_status != Case.LifecycleStatus.ACTIVE:
        raise ValueError("برای پرونده بایگانی‌شده نمی‌توان اقدام جدید ساخت.")
    action = CaseAction.objects.create(
        case=case,
        title=title,
        description=description.strip(),
        action_type=CaseAction.ActionType.MANUAL,
        priority=CaseAction.Priority.NORMAL,
        due_at=due_at,
        created_by=user,
        source_event="user.manual",
    )
    CaseEvent.objects.create(
        case=case,
        event_type="case.action_created",
        actor=user,
        payload={"action_id": str(action.id), "manual": True},
    )
    if due_at is not None:
        from .reminders import ensure_action_reminder
        ensure_action_reminder(action, user=user)
    return action


@transaction.atomic
def complete_case_action(*, case: Case, action_id, user) -> CaseAction:
    action = CaseAction.objects.select_for_update().get(pk=action_id, case=case)
    if action.system_key:
        raise ValueError("اقدام‌های سیستمی با تغییر وضعیت پرونده تکمیل می‌شوند.")
    action.status = CaseAction.Status.DONE
    action.completed_at = timezone.now()
    action.save(update_fields=["status", "completed_at", "updated_at"])
    CaseEvent.objects.create(
        case=case,
        event_type="case.action_completed",
        actor=user,
        payload={"action_id": str(action.id)},
    )
    from .reminders import cancel_action_reminders
    cancel_action_reminders(action)
    return action

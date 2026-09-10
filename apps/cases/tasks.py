from celery import shared_task

from .reminders import (
    claim_due_reminders,
    deliver_reminder,
    mark_reminder_failed,
    mark_reminder_sent,
)


@shared_task
def dispatch_due_reminders() -> dict:
    claimed = claim_due_reminders(limit=50)
    sent = 0
    failed = 0
    for reminder in claimed:
        try:
            deliver_reminder(reminder)
        except Exception as exc:
            mark_reminder_failed(reminder.id, exc)
            failed += 1
        else:
            mark_reminder_sent(reminder.id)
            sent += 1
    return {"claimed": len(claimed), "sent": sent, "failed": failed}

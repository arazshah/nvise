from __future__ import annotations

import logging

from celery.signals import task_failure

logger = logging.getLogger(__name__)


@task_failure.connect
def capture_task_failure(sender=None, task_id=None, exception=None, traceback=None, **kwargs):
    if not task_id:
        return
    try:
        from .models import TaskFailure

        request = getattr(sender, "request", None)
        TaskFailure.objects.update_or_create(
            task_id=str(task_id),
            defaults={
                "task_name": getattr(sender, "name", "") or "unknown",
                "exception_class": exception.__class__.__name__ if exception else "",
                "exception_message": str(exception or "")[:4000],
                "traceback": str(traceback or "")[-12000:],
                "retries": int(getattr(request, "retries", 0) or 0),
                "resolved": False,
                "resolved_at": None,
                "resolution_note": "",
            },
        )
    except Exception:
        logger.exception(
            "dead_letter_capture_failed",
            extra={
                "event": "celery.dead_letter.capture_failed",
                "task_id": str(task_id),
                "task_name": getattr(sender, "name", "") or "unknown",
            },
        )

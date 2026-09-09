from __future__ import annotations

import logging

from .models import AuditEvent

logger = logging.getLogger(__name__)


def record_audit_event(
    *,
    event_type: str,
    tenant=None,
    actor=None,
    case=None,
    object_type: str = "",
    object_id: str = "",
    request_id: str = "",
    source: str = "system",
    metadata: dict | None = None,
) -> AuditEvent | None:
    try:
        return AuditEvent.objects.create(
            tenant=tenant or getattr(case, "tenant", None),
            actor=actor,
            case=case,
            event_type=event_type,
            object_type=object_type,
            object_id=str(object_id or ""),
            request_id=request_id,
            source=source,
            metadata=metadata or {},
        )
    except Exception:
        logger.exception("audit_event_write_failed", extra={"audit_event_type": event_type})
        return None

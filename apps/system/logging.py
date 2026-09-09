from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timezone

request_id_var = contextvars.ContextVar("request_id", default="")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", "") or request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "") or request_id_var.get(),
        }
        for key in (
            "event",
            "tenant_id",
            "case_id",
            "task_id",
            "task_name",
            "audit_event_type",
        ):
            value = getattr(record, key, None)
            if value not in (None, ""):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)

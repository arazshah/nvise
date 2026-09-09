from __future__ import annotations

import logging
import time
import uuid

from .logging import request_id_var

logger = logging.getLogger("nvise.request")


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = (request.headers.get("X-Request-ID") or "").strip()[:64] or uuid.uuid4().hex
        request.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.monotonic()
        try:
            response = self.get_response(request)
            duration_ms = round((time.monotonic() - started) * 1000, 2)
            response["X-Request-ID"] = request_id
            logger.info(
                "request_completed",
                extra={
                    "event": "http.request.completed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        except Exception:
            logger.exception(
                "request_failed",
                extra={
                    "event": "http.request.failed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.path,
                },
            )
            raise
        finally:
            request_id_var.reset(token)

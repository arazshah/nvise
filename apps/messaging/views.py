import json

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.system.rate_limit import allow_fixed_window

from .models import InboundUpdate
from .providers.bale import BaleProvider
from .tasks import process_bale_update


@csrf_exempt
@require_POST
def bale_webhook(request: HttpRequest, secret: str) -> JsonResponse:
    configured_secret = settings.BALE_WEBHOOK_SECRET
    if not configured_secret or not constant_time_compare(secret, configured_secret):
        return JsonResponse({"ok": False}, status=404)

    remote_addr = request.META.get("REMOTE_ADDR", "unknown")
    if not allow_fixed_window(
        namespace="bale_webhook",
        key=remote_addr,
        limit=settings.BALE_WEBHOOK_RATE_LIMIT_PER_MINUTE,
        window_seconds=60,
    ):
        response = JsonResponse({"ok": False, "error": "rate_limited"}, status=429)
        response["Retry-After"] = "60"
        return response

    if len(request.body) > settings.MAX_WEBHOOK_BODY_BYTES:
        return JsonResponse({"ok": False, "error": "payload_too_large"}, status=413)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"ok": False, "error": "invalid_payload"}, status=400)

    normalized = BaleProvider().parse_update(payload)
    if not normalized.update_id:
        return JsonResponse({"ok": False, "error": "missing_update_id"}, status=400)

    with transaction.atomic():
        inbound, created = InboundUpdate.objects.get_or_create(
            provider="bale",
            bot_id=settings.BALE_BOT_ID,
            external_update_id=normalized.update_id,
            defaults={"payload": payload},
        )
        if created:
            transaction.on_commit(lambda: process_bale_update.delay(str(inbound.id)))

    return JsonResponse({"ok": True, "duplicate": not created})

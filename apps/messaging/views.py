import json

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.subscriptions.payments import PaymentError, answer_precheckout
from apps.system.integrations import get_bale_config
from apps.system.rate_limit import allow_fixed_window

from .models import InboundUpdate
from .providers.bale import BaleProvider
from .tasks import process_bale_update


@csrf_exempt
@require_POST
def bale_webhook(request: HttpRequest, secret: str) -> JsonResponse:
    config = get_bale_config()
    configured_secret = config.webhook_secret
    if not config.enabled or not configured_secret or not constant_time_compare(secret, configured_secret):
        return JsonResponse({"ok": False}, status=404)

    remote_addr = request.META.get("REMOTE_ADDR", "unknown")
    if not allow_fixed_window(
        namespace="bale_webhook",
        key=remote_addr,
        limit=config.rate_limit_per_minute,
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
            bot_id=config.bot_id,
            external_update_id=normalized.update_id,
            defaults={"payload": payload},
        )

    precheckout = payload.get("pre_checkout_query")
    if isinstance(precheckout, dict):
        try:
            approved = answer_precheckout(precheckout)
        except PaymentError as exc:
            inbound.processing_error = str(exc)[:2000]
            inbound.save(update_fields=["processing_error"])
            return JsonResponse({"ok": False, "error": "payment_precheckout_failed"}, status=503)
        inbound.processed_at = timezone.now()
        inbound.processing_error = ""
        inbound.save(update_fields=["processed_at", "processing_error"])
        return JsonResponse({"ok": True, "duplicate": not created, "payment_approved": approved})

    if created:
        transaction.on_commit(lambda: process_bale_update.delay(str(inbound.id)))

    return JsonResponse({"ok": True, "duplicate": not created})

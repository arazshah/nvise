import json

import redis
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.system.integrations import get_avalai_config, get_bale_config
from apps.system.models import TaskFailure


class Command(BaseCommand):
    help = "Validate operational prerequisites for the fire-loss pilot."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        checks: dict[str, dict] = {}

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            checks["database"] = {"ok": True}
        except Exception as exc:
            checks["database"] = {"ok": False, "error": exc.__class__.__name__}

        try:
            client = redis.Redis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            checks["redis"] = {"ok": bool(client.ping())}
        except Exception as exc:
            checks["redis"] = {"ok": False, "error": exc.__class__.__name__}

        bale = get_bale_config()
        avalai = get_avalai_config()
        configured = {
            "bale_enabled": bale.enabled,
            "bale_bot_token": bool(bale.bot_token),
            "bale_webhook_secret": bool(bale.webhook_secret),
            "avalai_enabled": avalai.enabled,
            "avalai_api_key": bool(avalai.api_key),
            "avalai_text_model": bool(avalai.text_model),
            "avalai_stt_model": bool(avalai.stt_model),
            "https_web_base_url": settings.WEB_BASE_URL.startswith("https://"),
        }
        for key, ok in configured.items():
            checks[key] = {"ok": ok}

        try:
            schema = ensure_fire_loss_schema()
            checks["fire_loss_schema"] = {
                "ok": True,
                "schema_id": str(schema.id),
                "version": schema.version,
                "field_count": schema.fields.count(),
            }
        except Exception as exc:
            checks["fire_loss_schema"] = {"ok": False, "error": exc.__class__.__name__}

        unresolved = TaskFailure.objects.filter(resolved=False).count()
        checks["dead_letter_queue"] = {"ok": unresolved == 0, "unresolved": unresolved}

        payload = {
            "ready": all(item.get("ok") is True for item in checks.values()),
            "checks": checks,
        }
        if options["as_json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, default=str))
        else:
            for name, result in checks.items():
                marker = "OK" if result.get("ok") else "FAIL"
                self.stdout.write(f"[{marker}] {name}: {result}")

        if not payload["ready"]:
            raise CommandError("Pilot readiness checks failed")
        self.stdout.write(self.style.SUCCESS("Fire-loss pilot readiness checks passed"))

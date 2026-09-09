from asgiref.sync import async_to_sync
from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import BaleIdentity
from apps.tenants.models import Tenant, TenantMembership

from .models import ConversationState, InboundUpdate
from .providers.bale import BaleProvider


WELCOME_TEXT = (
    "سلام، به نویسه خوش آمدید.\n\n"
    "نویسه پیام‌های صوتی و متنی شما را به گزارش حرفه‌ای تبدیل می‌کند.\n\n"
    "نسخه اولیه برای کارشناسان ارزیابی خسارت بیمه طراحی شده است."
)


def _resolve_bale_user(message):
    User = get_user_model()
    username = f"bale_{message.external_user_id}"
    display_name = " ".join(
        part
        for part in [
            (message.raw or {}).get("from", {}).get("first_name"),
            (message.raw or {}).get("from", {}).get("last_name"),
        ]
        if part
    ).strip()

    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"display_name": display_name},
    )
    identity, identity_created = BaleIdentity.objects.get_or_create(
        external_user_id=message.external_user_id,
        defaults={
            "user": user,
            "external_chat_id": message.external_chat_id,
            "username": (message.raw or {}).get("from", {}).get("username", ""),
            "first_name": (message.raw or {}).get("from", {}).get("first_name", ""),
            "last_name": (message.raw or {}).get("from", {}).get("last_name", ""),
        },
    )

    if identity.user_id != user.id:
        user = identity.user

    if identity.external_chat_id != message.external_chat_id:
        identity.external_chat_id = message.external_chat_id
        identity.save(update_fields=["external_chat_id", "updated_at"])

    if identity_created or not user.tenant_memberships.exists():
        tenant, _ = Tenant.objects.get_or_create(
            slug=f"personal-{user.id}",
            defaults={"name": display_name or "حساب شخصی نویسه"},
        )
        TenantMembership.objects.get_or_create(
            tenant=tenant,
            user=user,
            defaults={"role": TenantMembership.Role.OWNER},
        )

    return user


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def process_bale_update(self, inbound_update_id: str) -> None:
    inbound = InboundUpdate.objects.get(pk=inbound_update_id)
    provider = BaleProvider(settings.BALE_BOT_TOKEN)
    normalized = provider.parse_update(inbound.payload)

    if normalized.message is None:
        inbound.processed_at = timezone.now()
        inbound.processing_error = ""
        inbound.save(update_fields=["processed_at", "processing_error"])
        return

    try:
        with transaction.atomic():
            user = _resolve_bale_user(normalized.message)
            ConversationState.objects.get_or_create(
                user=user,
                provider="bale",
                external_chat_id=normalized.message.external_chat_id,
            )

        if (normalized.message.text or "").strip().lower() == "/start":
            if settings.BALE_BOT_TOKEN:
                async_to_sync(provider.send_text)(
                    normalized.message.external_chat_id,
                    WELCOME_TEXT,
                )

        inbound.processed_at = timezone.now()
        inbound.processing_error = ""
        inbound.save(update_fields=["processed_at", "processing_error"])
    except Exception as exc:
        inbound.processing_error = str(exc)[:2000]
        inbound.save(update_fields=["processing_error"])
        raise

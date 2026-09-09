from asgiref.sync import async_to_sync
from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import BaleIdentity
from apps.intelligence.actions import handle_analysis_action
from apps.portal.services import create_portal_access_token
from apps.subscriptions.models import UsageRecord
from apps.subscriptions.payments import PaymentError, process_successful_payment
from apps.subscriptions.services import (
    QuotaExceededError,
    SubscriptionAccessError,
    get_or_create_subscription,
    refresh_subscription_state,
)
from apps.system.integrations import get_bale_config
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.services import MemberLimitExceededError, add_tenant_member

from .handlers import handle_message, main_menu_keyboard
from .models import InboundUpdate
from .providers.bale import BaleProvider
from .providers.bale.provider import BILLING_LABEL, PORTAL_LOGIN_LABEL


SUBSCRIPTION_STATUS_LABELS = {
    "trialing": "دوره آزمایشی",
    "active": "فعال",
    "past_due": "نیازمند پیگیری پرداخت",
    "cancelled": "لغو شده",
    "expired": "منقضی شده",
}


def _resolve_bale_user(message):
    User = get_user_model()
    username = f"bale_{message.external_user_id}"
    sender = (message.raw or {}).get("from", {})
    display_name = " ".join(
        part for part in [sender.get("first_name"), sender.get("last_name")] if part
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
            "username": sender.get("username", ""),
            "first_name": sender.get("first_name", ""),
            "last_name": sender.get("last_name", ""),
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
        add_tenant_member(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)

    membership = (
        user.tenant_memberships.select_related("tenant")
        .filter(is_active=True, tenant__is_active=True)
        .order_by("created_at")
        .first()
    )
    if membership is not None:
        get_or_create_subscription(membership.tenant)

    return user


def _finish_non_retryable(inbound, provider, message, exc: Exception) -> None:
    inbound.processed_at = timezone.now()
    inbound.processing_error = str(exc)[:2000]
    inbound.save(update_fields=["processed_at", "processing_error"])
    if getattr(provider, "client", None) is not None:
        async_to_sync(provider.send_text)(
            message.external_chat_id,
            "سهمیه حساب شما برای این عملیات به پایان رسیده است. "
            "از «💳 اشتراک و مصرف» وضعیت استفاده را ببینید یا پلن حساب را ارتقا دهید.",
            main_menu_keyboard(),
        )


def _finish_subscription_block(inbound, provider, message, exc: SubscriptionAccessError) -> None:
    inbound.processed_at = timezone.now()
    inbound.processing_error = str(exc)[:2000]
    inbound.save(update_fields=["processed_at", "processing_error"])
    if getattr(provider, "client", None) is None:
        return

    if exc.code == "trial_expired":
        text = (
            "⏳ دوره آزمایشی شما به پایان رسیده است.\n\n"
            "پرونده‌ها، مدارک و گزارش‌های قبلی شما کاملاً حفظ شده‌اند؛ فقط عملیات هزینه‌دار مثل "
            "تبدیل صوت و تحلیل هوشمند تا فعال‌کردن یک پلن متوقف می‌شوند.\n\n"
            "💳 برای مشاهده وضعیت حساب روی «اشتراک و مصرف» بزنید.\n"
            "🌐 برای انتخاب پلن و پرداخت، وارد پنل نویسه شوید."
        )
    else:
        text = (
            f"⚠️ {exc}\n\n"
            "پرونده‌ها و اطلاعات شما حفظ شده‌اند. برای ادامه عملیات هوشمند وضعیت اشتراک را بررسی کنید."
        )
    async_to_sync(provider.send_text)(message.external_chat_id, text, main_menu_keyboard())


def _send_portal_access_link(*, provider, user, message) -> None:
    raw_token = create_portal_access_token(
        user=user,
        provider=message.provider,
        external_chat_id=message.external_chat_id,
        ttl_minutes=settings.PORTAL_LINK_TTL_MINUTES,
    )
    path = reverse("portal:portal-access", kwargs={"token": raw_token})
    url = f"{settings.WEB_BASE_URL}{path}"
    async_to_sync(provider.send_text)(
        message.external_chat_id,
        "🔐 ورود امن به پنل نویسه\n\n"
        "این لینک فقط برای حساب بله شما ساخته شده، یک‌بار قابل استفاده است و "
        f"تا {settings.PORTAL_LINK_TTL_MINUTES} دقیقه اعتبار دارد.\n\n"
        f"🌐 {url}\n\n"
        "پس از ورود موفق، همین لینک دیگر قابل استفاده نخواهد بود.",
    )


def _show_billing_summary(*, provider, user, message) -> None:
    membership = (
        user.tenant_memberships.select_related("tenant", "tenant__subscription__plan")
        .filter(is_active=True, tenant__is_active=True)
        .order_by("created_at")
        .first()
    )
    if membership is None:
        async_to_sync(provider.send_text)(
            message.external_chat_id,
            "⚠️ حساب فعالی برای نمایش اشتراک پیدا نشد.",
            main_menu_keyboard(),
        )
        return

    tenant = membership.tenant
    subscription = refresh_subscription_state(tenant)
    plan = subscription.plan
    usage = {
        row["metric"]: row["total"]
        for row in UsageRecord.objects.filter(
            tenant=tenant,
            occurred_at__gte=subscription.current_period_start,
            occurred_at__lt=subscription.current_period_end,
        )
        .values("metric")
        .annotate(total=Sum("quantity"))
    }

    cases = usage.get(UsageRecord.Metric.CASE_CREATED, 0)
    stt = usage.get(UsageRecord.Metric.STT_SECONDS, 0)
    ai = usage.get(UsageRecord.Metric.AI_EXTRACTION, 0)
    docs = usage.get(UsageRecord.Metric.DOCUMENT_GENERATED, 0)
    status = SUBSCRIPTION_STATUS_LABELS.get(subscription.status, subscription.status)
    is_expired = subscription.status == "expired" or subscription.current_period_end <= timezone.now()
    trial_note = "\n🎁 این پلن یک‌بار و به مدت ۳۰ روز ارائه می‌شود." if plan.code == "trial" else ""
    expired_note = (
        "\n\n⛔ اعتبار این دوره تمام شده است. پرونده‌های شما حفظ می‌شوند، اما STT و تحلیل هوشمند "
        "تا خرید پلن متوقف هستند."
        if is_expired
        else ""
    )

    text = (
        "💳 اشتراک و مصرف\n"
        "━━━━━━━━━━━━━━\n"
        f"🏢 حساب: {tenant.name}\n"
        f"📦 پلن: {plan.name}\n"
        f"✅ وضعیت: {status}\n"
        f"📅 اعتبار تا: {subscription.current_period_end:%Y/%m/%d}"
        f"{trial_note}\n\n"
        "📊 مصرف دوره جاری\n"
        f"📁 پرونده: {cases} از {plan.max_cases_per_period}\n"
        f"🎙 تبدیل صوت: {stt} از {plan.max_stt_seconds_per_period} ثانیه\n"
        f"🧠 تحلیل هوشمند: {ai} از {plan.max_ai_extractions_per_period}\n"
        f"📄 سند تولیدشده: {docs}"
        f"{expired_note}\n\n"
        "برای خرید، تمدید یا تغییر پلن از «🌐 ورود به پنل نویسه» استفاده کنید؛ "
        "صورتحساب نهایی داخل همین گفتگوی بله برای شما ارسال می‌شود."
    )
    async_to_sync(provider.send_text)(message.external_chat_id, text, main_menu_keyboard())


def _handle_successful_payment(*, inbound, provider, message) -> None:
    attempt, subscription, activated = process_successful_payment(message.raw or {})
    if activated:
        text = (
            "✅ پرداخت با موفقیت تأیید شد.\n\n"
            f"💳 پلن: {attempt.plan.name}\n"
            f"💰 مبلغ: {attempt.amount:,} ریال\n"
            f"📅 اعتبار تا: {subscription.current_period_end:%Y/%m/%d}\n\n"
            "اشتراک نویسه برای حساب شما فعال/تمدید شد."
        )
    else:
        text = "✅ این پرداخت قبلاً تأیید و روی اشتراک شما اعمال شده است."
    async_to_sync(provider.send_text)(message.external_chat_id, text, main_menu_keyboard())
    inbound.processed_at = timezone.now()
    inbound.processing_error = ""
    inbound.save(update_fields=["processed_at", "processing_error"])


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def process_bale_update(self, inbound_update_id: str) -> None:
    inbound = InboundUpdate.objects.get(pk=inbound_update_id)
    config = get_bale_config()
    if not config.enabled or not config.bot_token:
        raise RuntimeError("Bale integration is disabled or Bot Token is not configured")
    provider = BaleProvider(config.bot_token)
    normalized = provider.parse_update(inbound.payload)

    if normalized.message is None:
        inbound.processed_at = timezone.now()
        inbound.processing_error = ""
        inbound.save(update_fields=["processed_at", "processing_error"])
        return

    try:
        with transaction.atomic():
            user = _resolve_bale_user(normalized.message)

        if (normalized.message.raw or {}).get("successful_payment"):
            _handle_successful_payment(
                inbound=inbound,
                provider=provider,
                message=normalized.message,
            )
            return

        message_text = (normalized.message.text or "").strip()
        if message_text == PORTAL_LOGIN_LABEL:
            _send_portal_access_link(provider=provider, user=user, message=normalized.message)
        elif message_text == BILLING_LABEL:
            _show_billing_summary(provider=provider, user=user, message=normalized.message)
        elif handle_analysis_action(
            provider=provider,
            user=user,
            message=normalized.message,
        ):
            pass
        else:
            handle_message(
                inbound=inbound,
                provider=provider,
                user=user,
                message=normalized.message,
            )

        inbound.processed_at = timezone.now()
        inbound.processing_error = ""
        inbound.save(update_fields=["processed_at", "processing_error"])
    except SubscriptionAccessError as exc:
        _finish_subscription_block(inbound, provider, normalized.message, exc)
        return
    except (QuotaExceededError, MemberLimitExceededError) as exc:
        _finish_non_retryable(inbound, provider, normalized.message, exc)
        return
    except PaymentError as exc:
        inbound.processed_at = timezone.now()
        inbound.processing_error = str(exc)[:2000]
        inbound.save(update_fields=["processed_at", "processing_error"])
        async_to_sync(provider.send_text)(
            normalized.message.external_chat_id,
            "⚠️ پرداخت دریافت شد اما برای اعمال روی اشتراک نیاز به بررسی دارد. "
            "لطفاً با پشتیبانی نویسه تماس بگیرید.",
            main_menu_keyboard(),
        )
        return
    except Exception as exc:
        inbound.processing_error = str(exc)[:2000]
        inbound.save(update_fields=["processing_error"])
        raise

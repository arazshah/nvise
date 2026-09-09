from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import BaleIdentity
from apps.messaging.providers.bale.client import BaleClient
from apps.system.models import IntegrationSettings
from apps.tenants.models import Tenant, TenantMembership

from .models import PaymentAttempt, Plan, Subscription


class PaymentError(RuntimeError):
    pass


PAYMENT_ROLES = {TenantMembership.Role.OWNER, TenantMembership.Role.ADMIN}


def _settings() -> IntegrationSettings:
    integration = IntegrationSettings.objects.filter(pk=1).first()
    if integration is None:
        raise PaymentError("تنظیمات پرداخت نویسه هنوز ایجاد نشده است.")
    if not integration.online_payment_enabled:
        raise PaymentError("پرداخت آنلاین در حال حاضر غیرفعال است.")
    if not integration.bale_payment_token:
        raise PaymentError("توکن پرداخت کیف پول بله در پنل مدیریت تنظیم نشده است.")
    if not integration.bale_bot_token or not integration.bale_enabled:
        raise PaymentError("اتصال ربات بله برای پرداخت آماده نیست.")
    return integration


def _plan_amount(plan: Plan) -> int:
    if not plan.is_active:
        raise PaymentError("این پلن در حال حاضر قابل خرید نیست.")
    if plan.currency.upper() != "IRR":
        raise PaymentError("پرداخت کیف پول بله فقط برای پلن‌های ریالی فعال است.")
    amount = Decimal(plan.monthly_price)
    if amount <= 0:
        raise PaymentError("برای این پلن مبلغ قابل پرداخت تعریف نشده است.")
    if amount != amount.to_integral_value():
        raise PaymentError("مبلغ پلن باید به‌صورت عدد صحیح ریال تعریف شود.")
    return int(amount)


def _assert_billing_access(*, user, tenant: Tenant) -> TenantMembership:
    membership = TenantMembership.objects.filter(
        tenant=tenant,
        user=user,
        is_active=True,
        tenant__is_active=True,
        role__in=PAYMENT_ROLES,
    ).first()
    if membership is None:
        raise PaymentError("فقط مالک یا مدیر حساب می‌تواند اشتراک را خرید یا تمدید کند.")
    return membership


def _bale_identity(user) -> BaleIdentity:
    identity = BaleIdentity.objects.filter(user=user, is_active=True).first()
    if identity is None or not identity.external_user_id or not identity.external_chat_id:
        raise PaymentError("برای پرداخت باید حساب شما به ربات نویسه در بله متصل باشد.")
    return identity


def create_and_send_invoice(*, user, tenant: Tenant, plan: Plan) -> PaymentAttempt:
    integration = _settings()
    _assert_billing_access(user=user, tenant=tenant)
    identity = _bale_identity(user)
    amount = _plan_amount(plan)

    attempt = PaymentAttempt.objects.create(
        tenant=tenant,
        user=user,
        plan=plan,
        payload=f"nvise:{uuid.uuid4().hex}",
        amount=amount,
        currency="IRR",
        external_user_id=identity.external_user_id,
        external_chat_id=identity.external_chat_id,
    )

    try:
        result = async_to_sync(BaleClient(integration.bale_bot_token).send_invoice)(
            chat_id=identity.external_chat_id,
            title=(f"اشتراک {plan.name}")[:32],
            description=(f"خرید یا تمدید یک‌ماهه پلن {plan.name} نویسه")[:255],
            payload=attempt.payload,
            provider_token=integration.bale_payment_token,
            prices=[{"label": f"پلن {plan.name}", "amount": amount}],
        )
    except Exception as exc:
        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            status=PaymentAttempt.Status.FAILED,
            failure_reason=str(exc)[:500],
        )
        raise PaymentError("ارسال صورتحساب به بله ناموفق بود. دوباره تلاش کنید.") from exc

    attempt.status = PaymentAttempt.Status.INVOICE_SENT
    attempt.invoice_message_id = str((result or {}).get("message_id", ""))
    attempt.invoice_sent_at = timezone.now()
    attempt.save(update_fields=["status", "invoice_message_id", "invoice_sent_at", "updated_at"])
    return attempt


def validate_precheckout(precheckout: dict) -> tuple[bool, str, PaymentAttempt | None]:
    query_id = str(precheckout.get("id") or "")
    sender_id = str((precheckout.get("from") or {}).get("id") or "")
    payload = str(precheckout.get("invoice_payload") or "")
    currency = str(precheckout.get("currency") or "").upper()
    try:
        amount = int(precheckout.get("total_amount"))
    except (TypeError, ValueError):
        amount = -1

    if not query_id or not payload:
        return False, "اطلاعات پرداخت ناقص است. لطفاً صورتحساب جدید دریافت کنید.", None

    with transaction.atomic():
        attempt = PaymentAttempt.objects.select_for_update().select_related("plan").filter(payload=payload).first()
        if attempt is None:
            return False, "این صورتحساب در نویسه شناخته نشد.", None

        if attempt.status == PaymentAttempt.Status.PAID:
            return False, "این صورتحساب قبلاً پرداخت شده است.", attempt
        if attempt.status not in {
            PaymentAttempt.Status.INVOICE_SENT,
            PaymentAttempt.Status.PRECHECKOUT_APPROVED,
        }:
            return False, "این صورتحساب دیگر قابل پرداخت نیست.", attempt

        errors = []
        if sender_id != attempt.external_user_id:
            errors.append("هویت پرداخت‌کننده با صاحب صورتحساب مطابقت ندارد")
        if currency != attempt.currency:
            errors.append("واحد پول صورتحساب معتبر نیست")
        if amount != attempt.amount:
            errors.append("مبلغ صورتحساب با مبلغ ثبت‌شده مطابقت ندارد")
        if not attempt.plan.is_active:
            errors.append("پلن انتخاب‌شده دیگر فعال نیست")

        integration = IntegrationSettings.objects.filter(pk=1).first()
        if not integration or not integration.online_payment_enabled or not integration.bale_payment_token:
            errors.append("پرداخت نویسه موقتاً غیرفعال است")

        if errors:
            attempt.status = PaymentAttempt.Status.REJECTED
            attempt.failure_reason = "؛ ".join(errors)[:500]
            attempt.raw_precheckout = precheckout
            attempt.pre_checkout_query_id = query_id
            attempt.precheckout_at = timezone.now()
            attempt.save(update_fields=[
                "status", "failure_reason", "raw_precheckout", "pre_checkout_query_id", "precheckout_at", "updated_at"
            ])
            return False, "امکان تأیید این پرداخت وجود ندارد؛ لطفاً صورتحساب جدید دریافت کنید.", attempt

        if attempt.pre_checkout_query_id and attempt.pre_checkout_query_id != query_id:
            return False, "این صورتحساب در یک تراکنش دیگر در حال پردازش است.", attempt

        attempt.status = PaymentAttempt.Status.PRECHECKOUT_APPROVED
        attempt.pre_checkout_query_id = query_id
        attempt.raw_precheckout = precheckout
        attempt.precheckout_at = timezone.now()
        attempt.failure_reason = ""
        attempt.save(update_fields=[
            "status", "pre_checkout_query_id", "raw_precheckout", "precheckout_at", "failure_reason", "updated_at"
        ])
        return True, "", attempt


def answer_precheckout(precheckout: dict) -> bool:
    integration = IntegrationSettings.objects.filter(pk=1).first()
    if integration is None or not integration.bale_bot_token:
        raise PaymentError("توکن ربات بله برای پاسخ پرداخت تنظیم نشده است.")
    ok, error_message, _attempt = validate_precheckout(precheckout)
    query_id = str(precheckout.get("id") or "")
    async_to_sync(BaleClient(integration.bale_bot_token).answer_pre_checkout_query)(
        pre_checkout_query_id=query_id,
        ok=ok,
        error_message=error_message or None,
    )
    return ok


def _activate_subscription(*, attempt: PaymentAttempt) -> Subscription:
    now = timezone.now()
    subscription = Subscription.objects.select_for_update().filter(tenant=attempt.tenant).first()
    if subscription is None:
        return Subscription.objects.create(
            tenant=attempt.tenant,
            plan=attempt.plan,
            status=Subscription.Status.ACTIVE,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            cancel_at_period_end=False,
            metadata={"last_payment_attempt": str(attempt.id), "payment_provider": "bale"},
        )

    same_active_plan = (
        subscription.plan_id == attempt.plan_id
        and subscription.status in {Subscription.Status.ACTIVE, Subscription.Status.TRIALING}
        and subscription.current_period_end > now
    )
    if same_active_plan:
        subscription.current_period_end = subscription.current_period_end + timedelta(days=30)
    else:
        subscription.plan = attempt.plan
        subscription.current_period_start = now
        subscription.current_period_end = now + timedelta(days=30)

    metadata = dict(subscription.metadata or {})
    metadata.update({"last_payment_attempt": str(attempt.id), "payment_provider": "bale"})
    subscription.metadata = metadata
    subscription.status = Subscription.Status.ACTIVE
    subscription.cancel_at_period_end = False
    subscription.save(update_fields=[
        "plan", "status", "current_period_start", "current_period_end", "cancel_at_period_end", "metadata", "updated_at"
    ])
    return subscription


def process_successful_payment(message_payload: dict) -> tuple[PaymentAttempt, Subscription, bool]:
    successful = message_payload.get("successful_payment") or {}
    sender_id = str((message_payload.get("from") or {}).get("id") or "")
    payload = str(successful.get("invoice_payload") or "")
    currency = str(successful.get("currency") or "").upper()
    try:
        amount = int(successful.get("total_amount"))
    except (TypeError, ValueError):
        amount = -1
    charge_id = str(successful.get("telegram_payment_charge_id") or "")
    tracking_id = str(successful.get("provider_payment_charge_id") or "")

    if not payload or not charge_id:
        raise PaymentError("پیام پرداخت موفق بله ناقص است.")

    with transaction.atomic():
        attempt = PaymentAttempt.objects.select_for_update().select_related("tenant", "plan").filter(payload=payload).first()
        if attempt is None:
            raise PaymentError("پرداخت موفق برای صورتحساب ناشناخته دریافت شد.")

        if attempt.status == PaymentAttempt.Status.PAID:
            subscription = Subscription.objects.select_for_update().get(tenant=attempt.tenant)
            return attempt, subscription, False

        if sender_id != attempt.external_user_id:
            raise PaymentError("هویت پرداخت موفق با صورتحساب مطابقت ندارد.")
        if currency != attempt.currency or amount != attempt.amount:
            raise PaymentError("مبلغ یا واحد پول پرداخت موفق با صورتحساب مطابقت ندارد.")
        if attempt.pre_checkout_query_id and charge_id != attempt.pre_checkout_query_id:
            raise PaymentError("شناسه پرداخت موفق با pre-checkout تأییدشده مطابقت ندارد.")

        existing_charge = PaymentAttempt.objects.exclude(pk=attempt.pk).filter(
            provider_payment_charge_id=charge_id
        ).exists()
        if existing_charge:
            raise PaymentError("این شناسه پرداخت قبلاً پردازش شده است.")

        subscription = _activate_subscription(attempt=attempt)
        attempt.status = PaymentAttempt.Status.PAID
        attempt.provider_payment_charge_id = charge_id
        attempt.provider_tracking_id = tracking_id or None
        attempt.raw_successful_payment = successful
        attempt.paid_at = timezone.now()
        attempt.failure_reason = ""
        attempt.save(update_fields=[
            "status", "provider_payment_charge_id", "provider_tracking_id", "raw_successful_payment", "paid_at", "failure_reason", "updated_at"
        ])
        return attempt, subscription, True

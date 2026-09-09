import uuid

from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class Plan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    monthly_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="IRR")
    max_cases_per_period = models.PositiveIntegerField(default=5)
    max_stt_seconds_per_period = models.PositiveIntegerField(default=1800)
    max_ai_extractions_per_period = models.PositiveIntegerField(default=25)
    max_members = models.PositiveIntegerField(default=1)
    features = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class Subscription(models.Model):
    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    cancel_at_period_end = models.BooleanField(default=False)
    external_customer_id = models.CharField(max_length=128, blank=True)
    external_subscription_id = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PaymentAttempt(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        INVOICE_SENT = "invoice_sent", "Invoice sent"
        PRECHECKOUT_APPROVED = "precheckout_approved", "Pre-checkout approved"
        PAID = "paid", "Paid"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="payment_attempts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payment_attempts")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="payment_attempts")
    provider = models.CharField(max_length=24, default="bale")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.CREATED, db_index=True)
    payload = models.CharField(max_length=128, unique=True)
    amount = models.PositiveBigIntegerField(help_text="Amount in Iranian rials (IRR).")
    currency = models.CharField(max_length=8, default="IRR")
    external_user_id = models.CharField(max_length=128)
    external_chat_id = models.CharField(max_length=128)
    invoice_message_id = models.CharField(max_length=128, blank=True)
    pre_checkout_query_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    provider_payment_charge_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    provider_tracking_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    failure_reason = models.CharField(max_length=500, blank=True)
    raw_precheckout = models.JSONField(default=dict, blank=True)
    raw_successful_payment = models.JSONField(default=dict, blank=True)
    invoice_sent_at = models.DateTimeField(null=True, blank=True)
    precheckout_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status", "created_at"], name="pay_tenant_status_idx"),
            models.Index(fields=["external_user_id", "status"], name="pay_bale_user_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.plan.code}:{self.amount}:{self.status}"


class Entitlement(models.Model):
    class Source(models.TextChoices):
        PLAN = "plan", "Plan"
        OVERRIDE = "override", "Override"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="entitlements")
    key = models.SlugField(max_length=96)
    value = models.JSONField(default=dict)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.OVERRIDE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["subscription", "key"], name="uniq_subscription_entitlement")
        ]


class UsageRecord(models.Model):
    class Metric(models.TextChoices):
        CASE_CREATED = "case_created", "Case created"
        STT_SECONDS = "stt_seconds", "STT seconds"
        AI_EXTRACTION = "ai_extraction", "AI extraction"
        DOCUMENT_GENERATED = "document_generated", "Document generated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="usage_records")
    metric = models.CharField(max_length=40, choices=Metric.choices, db_index=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=1)
    idempotency_key = models.CharField(max_length=180, unique=True)
    case = models.ForeignKey(
        "cases.Case",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="usage_records",
    )
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["tenant", "metric", "occurred_at"], name="usage_tenant_metric_idx")]

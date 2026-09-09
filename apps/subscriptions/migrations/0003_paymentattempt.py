# Generated manually for Bale wallet subscription payments.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0002_seed_plans_and_backfill"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentAttempt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(default="bale", max_length=24)),
                ("status", models.CharField(choices=[("created", "Created"), ("invoice_sent", "Invoice sent"), ("precheckout_approved", "Pre-checkout approved"), ("paid", "Paid"), ("rejected", "Rejected"), ("failed", "Failed")], db_index=True, default="created", max_length=24)),
                ("payload", models.CharField(max_length=128, unique=True)),
                ("amount", models.PositiveBigIntegerField(help_text="Amount in Iranian rials (IRR).")),
                ("currency", models.CharField(default="IRR", max_length=8)),
                ("external_user_id", models.CharField(max_length=128)),
                ("external_chat_id", models.CharField(max_length=128)),
                ("invoice_message_id", models.CharField(blank=True, max_length=128)),
                ("pre_checkout_query_id", models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ("provider_payment_charge_id", models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ("provider_tracking_id", models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ("failure_reason", models.CharField(blank=True, max_length=500)),
                ("raw_precheckout", models.JSONField(blank=True, default=dict)),
                ("raw_successful_payment", models.JSONField(blank=True, default=dict)),
                ("invoice_sent_at", models.DateTimeField(blank=True, null=True)),
                ("precheckout_at", models.DateTimeField(blank=True, null=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payment_attempts", to="subscriptions.plan")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payment_attempts", to="tenants.tenant")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payment_attempts", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="paymentattempt",
            index=models.Index(fields=["tenant", "status", "created_at"], name="pay_tenant_status_idx"),
        ),
        migrations.AddIndex(
            model_name="paymentattempt",
            index=models.Index(fields=["external_user_id", "status"], name="pay_bale_user_status_idx"),
        ),
    ]

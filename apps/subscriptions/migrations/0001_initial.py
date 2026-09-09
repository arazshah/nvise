import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("cases", "0001_initial"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Plan",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                ("monthly_price", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("currency", models.CharField(default="IRR", max_length=8)),
                ("max_cases_per_period", models.PositiveIntegerField(default=5)),
                ("max_stt_seconds_per_period", models.PositiveIntegerField(default=1800)),
                ("max_ai_extractions_per_period", models.PositiveIntegerField(default=25)),
                ("max_members", models.PositiveIntegerField(default=1)),
                ("features", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("trialing", "Trialing"), ("active", "Active"), ("past_due", "Past due"), ("cancelled", "Cancelled"), ("expired", "Expired")], db_index=True, default="active", max_length=20)),
                ("current_period_start", models.DateTimeField()),
                ("current_period_end", models.DateTimeField()),
                ("cancel_at_period_end", models.BooleanField(default=False)),
                ("external_customer_id", models.CharField(blank=True, max_length=128)),
                ("external_subscription_id", models.CharField(blank=True, max_length=128)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="subscriptions", to="subscriptions.plan")),
                ("tenant", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="subscription", to="tenants.tenant")),
            ],
        ),
        migrations.CreateModel(
            name="Entitlement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("key", models.SlugField(max_length=96)),
                ("value", models.JSONField(default=dict)),
                ("source", models.CharField(choices=[("plan", "Plan"), ("override", "Override")], default="override", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("subscription", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entitlements", to="subscriptions.subscription")),
            ],
        ),
        migrations.CreateModel(
            name="UsageRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("metric", models.CharField(choices=[("case_created", "Case created"), ("stt_seconds", "STT seconds"), ("ai_extraction", "AI extraction"), ("document_generated", "Document generated")], db_index=True, max_length=40)),
                ("quantity", models.DecimalField(decimal_places=3, default=1, max_digits=14)),
                ("idempotency_key", models.CharField(max_length=180, unique=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("occurred_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("case", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="usage_records", to="cases.case")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="usage_records", to="tenants.tenant")),
            ],
            options={
                "indexes": [models.Index(fields=["tenant", "metric", "occurred_at"], name="usage_tenant_metric_idx")],
            },
        ),
        migrations.AddConstraint(
            model_name="entitlement",
            constraint=models.UniqueConstraint(fields=("subscription", "key"), name="uniq_subscription_entitlement"),
        ),
    ]

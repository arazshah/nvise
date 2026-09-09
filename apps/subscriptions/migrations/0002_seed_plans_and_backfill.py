from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def seed_plans_and_backfill(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Subscription = apps.get_model("subscriptions", "Subscription")
    Tenant = apps.get_model("tenants", "Tenant")

    free, _ = Plan.objects.get_or_create(
        code="free",
        defaults={
            "name": "Free",
            "monthly_price": 0,
            "currency": "IRR",
            "max_cases_per_period": 5,
            "max_stt_seconds_per_period": 1800,
            "max_ai_extractions_per_period": 25,
            "max_members": 1,
            "features": {"docx": True, "web_review": True},
        },
    )
    Plan.objects.get_or_create(
        code="pro",
        defaults={
            "name": "Pro",
            "monthly_price": 0,
            "currency": "IRR",
            "max_cases_per_period": 100,
            "max_stt_seconds_per_period": 36000,
            "max_ai_extractions_per_period": 500,
            "max_members": 5,
            "features": {"docx": True, "web_review": True, "priority_processing": True},
        },
    )

    now = timezone.now()
    period_end = now + timedelta(days=30)
    for tenant in Tenant.objects.all().iterator():
        Subscription.objects.get_or_create(
            tenant=tenant,
            defaults={
                "plan": free,
                "status": "active",
                "current_period_start": now,
                "current_period_end": period_end,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_plans_and_backfill, migrations.RunPython.noop),
    ]

from django.db import migrations


def seed_launch_plans(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Subscription = apps.get_model("subscriptions", "Subscription")

    trial, _ = Plan.objects.update_or_create(
        code="trial",
        defaults={
            "name": "آزمایشی ۳۰ روزه",
            "is_active": True,
            "monthly_price": 0,
            "currency": "IRR",
            "max_cases_per_period": 5,
            "max_stt_seconds_per_period": 1800,
            "max_ai_extractions_per_period": 15,
            "max_members": 1,
            "features": {
                "docx": True,
                "web_review": True,
                "priority_processing": False,
                "trial": True,
            },
        },
    )
    Plan.objects.update_or_create(
        code="pro",
        defaults={
            "name": "حرفه‌ای",
            "is_active": True,
            "monthly_price": 490000,
            "currency": "IRR",
            "max_cases_per_period": 50,
            "max_stt_seconds_per_period": 18000,
            "max_ai_extractions_per_period": 150,
            "max_members": 1,
            "features": {
                "docx": True,
                "web_review": True,
                "priority_processing": True,
                "full_analysis": True,
                "report_history": True,
            },
        },
    )
    Plan.objects.update_or_create(
        code="team",
        defaults={
            "name": "تیمی",
            "is_active": True,
            "monthly_price": 1490000,
            "currency": "IRR",
            "max_cases_per_period": 200,
            "max_stt_seconds_per_period": 72000,
            "max_ai_extractions_per_period": 600,
            "max_members": 5,
            "features": {
                "docx": True,
                "web_review": True,
                "priority_processing": True,
                "full_analysis": True,
                "report_history": True,
                "team_workspace": True,
            },
        },
    )

    legacy_free = Plan.objects.filter(code="free").first()
    if legacy_free is not None:
        for subscription in Subscription.objects.filter(plan=legacy_free).iterator():
            metadata = dict(subscription.metadata or {})
            metadata.setdefault("trial_granted", True)
            metadata.setdefault("legacy_free_converted", True)
            subscription.plan = trial
            if subscription.status == "active":
                subscription.status = "trialing"
            subscription.metadata = metadata
            subscription.save(update_fields=["plan", "status", "metadata", "updated_at"])
        legacy_free.is_active = False
        legacy_free.save(update_fields=["is_active", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0003_paymentattempt"),
    ]

    operations = [
        migrations.RunPython(seed_launch_plans, migrations.RunPython.noop),
    ]

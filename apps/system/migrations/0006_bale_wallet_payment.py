from django.db import migrations, models


def switch_existing_provider_to_bale(apps, schema_editor):
    IntegrationSettings = apps.get_model("system", "IntegrationSettings")
    IntegrationSettings.objects.all().update(
        payment_provider="bale",
        online_payment_enabled=False,
        billing_notice="پرداخت اشتراک از طریق کیف پول بله انجام خواهد شد.",
    )


class Migration(migrations.Migration):
    dependencies = [("system", "0005_product_and_billing_settings")]

    operations = [
        migrations.AddField(
            model_name="integrationsettings",
            name="bale_payment_token_encrypted",
            field=models.TextField(blank=True, editable=False),
        ),
        migrations.RunPython(switch_existing_provider_to_bale, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="integrationsettings",
            name="online_payment_enabled",
            field=models.BooleanField(
                default=False,
                help_text="فقط پس از تکمیل جریان sendInvoice و تأیید پرداخت بله فعال شود.",
            ),
        ),
        migrations.AlterField(
            model_name="integrationsettings",
            name="payment_provider",
            field=models.CharField(
                choices=[("bale", "کیف پول بله")],
                default="bale",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="integrationsettings",
            name="billing_notice",
            field=models.CharField(
                default="پرداخت اشتراک از طریق کیف پول بله انجام خواهد شد.",
                max_length=500,
            ),
        ),
        migrations.RemoveField(
            model_name="integrationsettings",
            name="zibal_merchant",
        ),
    ]

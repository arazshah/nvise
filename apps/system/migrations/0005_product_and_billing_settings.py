from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("system", "0004_integrationsettings_bale_public_url")]

    operations = [
        migrations.AddField(
            model_name="integrationsettings",
            name="creator_name",
            field=models.CharField(default="آراز شاه‌کرمی", max_length=160),
        ),
        migrations.AddField(
            model_name="integrationsettings",
            name="creator_url",
            field=models.URLField(default="https://araz.me"),
        ),
        migrations.AddField(
            model_name="integrationsettings",
            name="support_email",
            field=models.EmailField(default="mail@araz.me", max_length=254),
        ),
        migrations.AddField(
            model_name="integrationsettings",
            name="show_billing_portal",
            field=models.BooleanField(
                default=True,
                help_text="نمایش بخش اشتراک، مصرف و پلن‌ها در پنل کاربران.",
            ),
        ),
        migrations.AddField(
            model_name="integrationsettings",
            name="online_payment_enabled",
            field=models.BooleanField(
                default=False,
                help_text="فقط پس از تکمیل اتصال و تأیید جریان پرداخت فعال شود.",
            ),
        ),
        migrations.AddField(
            model_name="integrationsettings",
            name="payment_provider",
            field=models.CharField(
                choices=[("zibal", "زیبال")],
                default="zibal",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="integrationsettings",
            name="zibal_merchant",
            field=models.CharField(
                blank=True,
                help_text="Merchant زیبال. تا پیش از راه‌اندازی پرداخت آنلاین می‌تواند خالی بماند.",
                max_length=128,
            ),
        ),
        migrations.AddField(
            model_name="integrationsettings",
            name="billing_notice",
            field=models.CharField(
                default="پرداخت آنلاین به‌زودی از طریق زیبال فعال خواهد شد.",
                max_length=500,
            ),
        ),
    ]

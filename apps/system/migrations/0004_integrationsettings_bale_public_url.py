from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("system", "0003_seed_integration_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="integrationsettings",
            name="bale_public_url",
            field=models.URLField(
                blank=True,
                help_text="لینک عمومی ربات بله برای دکمه شروع در صفحه اصلی سایت.",
            ),
        ),
    ]

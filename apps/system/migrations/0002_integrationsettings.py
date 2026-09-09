from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("system", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="IntegrationSettings",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("avalai_enabled", models.BooleanField(default=True)),
                ("avalai_base_url", models.URLField(default="https://api.avalai.ir/v1")),
                ("avalai_text_model", models.CharField(default="gpt-5.6-luna", max_length=128)),
                ("avalai_stt_model", models.CharField(default="gpt-4o-mini-transcribe", max_length=128)),
                ("avalai_stt_language", models.CharField(default="fa", max_length=16)),
                ("avalai_timeout_seconds", models.PositiveIntegerField(default=120)),
                ("avalai_api_key_encrypted", models.TextField(blank=True, editable=False)),
                ("bale_enabled", models.BooleanField(default=True)),
                ("bale_bot_id", models.CharField(default="primary", max_length=128)),
                ("bale_bot_token_encrypted", models.TextField(blank=True, editable=False)),
                ("bale_webhook_secret_encrypted", models.TextField(blank=True, editable=False)),
                ("bale_webhook_rate_limit_per_minute", models.PositiveIntegerField(default=120)),
                ("last_avalai_test_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("last_avalai_test_ok", models.BooleanField(editable=False, null=True)),
                ("last_avalai_test_message", models.CharField(blank=True, editable=False, max_length=500)),
                ("last_bale_test_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("last_bale_test_ok", models.BooleanField(editable=False, null=True)),
                ("last_bale_test_message", models.CharField(blank=True, editable=False, max_length=500)),
                ("last_bale_webhook_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Integration settings",
                "verbose_name_plural": "Integration settings",
            },
        )
    ]

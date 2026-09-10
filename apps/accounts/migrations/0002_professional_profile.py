from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="profession_key",
            field=models.CharField(
                blank=True,
                choices=[
                    ("insurance_loss_adjuster", "کارشناس ارزیاب خسارت بیمه"),
                    ("lawyer", "وکیل / کارشناس حقوقی"),
                    ("technical_expert", "کارشناس / مشاور فنی"),
                    ("other", "سایر"),
                ],
                db_index=True,
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="specialty_key",
            field=models.CharField(blank=True, max_length=96),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="evidence",
            name="evidence_valid_source",
        ),
        migrations.AlterField(
            model_name="evidence",
            name="source_kind",
            field=models.CharField(
                choices=[
                    ("message", "Message"),
                    ("transcript_segment", "Transcript segment"),
                    ("document_page", "Document page"),
                    ("image_analysis", "Image analysis"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="evidence",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        source_kind="message",
                        message__isnull=False,
                        transcript_segment__isnull=True,
                    )
                    | models.Q(
                        source_kind="transcript_segment",
                        message__isnull=True,
                        transcript_segment__isnull=False,
                    )
                    | models.Q(
                        source_kind__in=["document_page", "image_analysis"],
                        message__isnull=False,
                        transcript_segment__isnull=True,
                    )
                ),
                name="evidence_valid_source",
            ),
        ),
    ]

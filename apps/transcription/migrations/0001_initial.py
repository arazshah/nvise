import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("processing", "0002_processingjob_uniq_attachment_job_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="Recording",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("duration_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("sample_rate_hz", models.PositiveIntegerField(blank=True, null=True)),
                ("channels", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("codec", models.CharField(blank=True, max_length=64)),
                ("language_hint", models.CharField(default="fa", max_length=16)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("transcribing", "Transcribing"), ("transcribed", "Transcribed"), ("failed", "Failed")], db_index=True, default="pending", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("attachment", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="recording", to="processing.caseattachment")),
            ],
        ),
        migrations.CreateModel(
            name="Transcript",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(max_length=64)),
                ("model_name", models.CharField(blank=True, max_length=128)),
                ("language", models.CharField(blank=True, max_length=16)),
                ("text", models.TextField(blank=True)),
                ("confidence", models.FloatField(blank=True, null=True)),
                ("raw_response", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("completed", "Completed"), ("failed", "Failed")], db_index=True, default="draft", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("processing_job", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="transcript", to="processing.processingjob")),
                ("recording", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="transcripts", to="transcription.recording")),
            ],
        ),
        migrations.CreateModel(
            name="TranscriptSegment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sequence", models.PositiveIntegerField()),
                ("start_ms", models.PositiveIntegerField()),
                ("end_ms", models.PositiveIntegerField()),
                ("text", models.TextField()),
                ("confidence", models.FloatField(blank=True, null=True)),
                ("speaker", models.CharField(blank=True, max_length=64)),
                ("transcript", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="segments", to="transcription.transcript")),
            ],
            options={
                "ordering": ["sequence"],
                "constraints": [models.UniqueConstraint(fields=("transcript", "sequence"), name="uniq_transcript_segment_sequence")],
            },
        ),
    ]

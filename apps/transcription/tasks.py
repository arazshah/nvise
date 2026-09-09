from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.processing.models import ProcessingAttempt, ProcessingJob
from apps.processing.storage import read_private_bytes

from .models import Recording, Transcript, TranscriptSegment
from .providers import get_stt_provider


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def transcribe_audio(self, job_id: str) -> None:
    with transaction.atomic():
        job = (
            ProcessingJob.objects.select_for_update()
            .select_related("attachment__message")
            .get(pk=job_id)
        )
        if job.status == ProcessingJob.Status.SUCCEEDED:
            return
        if job.job_type != ProcessingJob.JobType.TRANSCRIBE_AUDIO:
            raise RuntimeError("transcribe_audio received a non-transcription job")

        attachment = job.attachment
        if not attachment.storage_key:
            raise RuntimeError("Attachment has not been stored yet")

        job.status = ProcessingJob.Status.RUNNING
        job.started_at = timezone.now()
        job.attempts += 1
        job.last_error = ""
        job.save(update_fields=["status", "started_at", "attempts", "last_error", "updated_at"])

        attempt = ProcessingAttempt.objects.create(job=job, attempt_number=job.attempts)
        recording, _ = Recording.objects.select_for_update().get_or_create(
            attachment=attachment,
            defaults={"language_hint": "fa"},
        )
        recording.status = Recording.Status.TRANSCRIBING
        recording.save(update_fields=["status", "updated_at"])

    try:
        content = read_private_bytes(attachment.storage_key)
        provider = get_stt_provider()
        result = provider.transcribe(
            content=content,
            filename=attachment.original_name or "recording.bin",
            mime_type=attachment.mime_type or "application/octet-stream",
            language_hint=recording.language_hint or None,
        )

        with transaction.atomic():
            job = ProcessingJob.objects.select_for_update().get(pk=job.pk)
            recording = Recording.objects.select_for_update().get(pk=recording.pk)

            transcript, _ = Transcript.objects.select_for_update().get_or_create(
                processing_job=job,
                defaults={
                    "recording": recording,
                    "provider": provider.key,
                },
            )
            transcript.provider = provider.key
            transcript.model_name = result.model_name
            transcript.language = result.language
            transcript.text = result.text
            transcript.confidence = result.confidence
            transcript.raw_response = result.raw
            transcript.status = Transcript.Status.COMPLETED
            transcript.completed_at = timezone.now()
            transcript.save()

            transcript.segments.all().delete()
            TranscriptSegment.objects.bulk_create(
                [
                    TranscriptSegment(
                        transcript=transcript,
                        sequence=index,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        text=segment.text,
                        confidence=segment.confidence,
                        speaker=segment.speaker,
                    )
                    for index, segment in enumerate(result.segments)
                    if segment.text
                ]
            )

            recording.status = Recording.Status.TRANSCRIBED
            if result.segments:
                recording.duration_ms = max(segment.end_ms for segment in result.segments)
            recording.save(update_fields=["status", "duration_ms", "updated_at"])

            job.status = ProcessingJob.Status.SUCCEEDED
            job.finished_at = timezone.now()
            job.last_error = ""
            job.save(update_fields=["status", "finished_at", "last_error", "updated_at"])

            attempt = ProcessingAttempt.objects.select_for_update().get(pk=attempt.pk)
            attempt.succeeded = True
            attempt.finished_at = timezone.now()
            attempt.metadata = {
                "provider": provider.key,
                "model": result.model_name,
                "language": result.language,
                "segments": len(result.segments),
                "characters": len(result.text),
            }
            attempt.save(update_fields=["succeeded", "finished_at", "metadata"])

    except Exception as exc:
        with transaction.atomic():
            job = ProcessingJob.objects.select_for_update().get(pk=job.pk)
            recording = Recording.objects.select_for_update().get(pk=recording.pk)

            transcript, _ = Transcript.objects.select_for_update().get_or_create(
                processing_job=job,
                defaults={
                    "recording": recording,
                    "provider": "unknown",
                },
            )
            transcript.status = Transcript.Status.FAILED
            transcript.completed_at = timezone.now()
            transcript.save(update_fields=["status", "completed_at"])

            recording.status = Recording.Status.FAILED
            recording.save(update_fields=["status", "updated_at"])

            job.status = ProcessingJob.Status.FAILED
            job.finished_at = timezone.now()
            job.last_error = str(exc)[:2000]
            job.save(update_fields=["status", "finished_at", "last_error", "updated_at"])

            attempt = ProcessingAttempt.objects.select_for_update().get(pk=attempt.pk)
            attempt.finished_at = timezone.now()
            attempt.error_class = exc.__class__.__name__
            attempt.error_message = str(exc)[:2000]
            attempt.save(update_fields=["finished_at", "error_class", "error_message"])
        raise

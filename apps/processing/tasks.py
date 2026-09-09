from asgiref.sync import async_to_sync
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.messaging.models import CaseMessage
from apps.messaging.providers.bale import BaleProvider
from apps.messaging.providers.bale.client import BaleFileTooLargeError

from .models import CaseAttachment, ProcessingAttempt, ProcessingJob
from .storage import store_private_bytes


def _next_job_type(message_type: str) -> str | None:
    if message_type in {CaseMessage.MessageType.VOICE, CaseMessage.MessageType.AUDIO}:
        return ProcessingJob.JobType.TRANSCRIBE_AUDIO
    if message_type == CaseMessage.MessageType.DOCUMENT:
        return ProcessingJob.JobType.EXTRACT_DOCUMENT
    if message_type == CaseMessage.MessageType.IMAGE:
        return ProcessingJob.JobType.ANALYZE_IMAGE
    return None


def _enqueue_next_job(job: ProcessingJob) -> None:
    if job.job_type == ProcessingJob.JobType.TRANSCRIBE_AUDIO:
        from apps.transcription.tasks import transcribe_audio

        transcribe_audio.delay(str(job.id))


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def fetch_attachment(self, job_id: str) -> None:
    with transaction.atomic():
        job = ProcessingJob.objects.select_for_update().select_related(
            "attachment__message"
        ).get(pk=job_id)
        if job.status == ProcessingJob.Status.SUCCEEDED:
            return
        if job.job_type != ProcessingJob.JobType.FETCH_ATTACHMENT:
            raise RuntimeError("fetch_attachment received a non-fetch job")

        job.status = ProcessingJob.Status.RUNNING
        job.started_at = timezone.now()
        job.attempts += 1
        job.last_error = ""
        job.save(update_fields=["status", "started_at", "attempts", "last_error", "updated_at"])
        attempt = ProcessingAttempt.objects.create(job=job, attempt_number=job.attempts)
        attachment = job.attachment
        attachment.status = CaseAttachment.Status.FETCHING
        attachment.error_code = ""
        attachment.error_message = ""
        attachment.save(update_fields=["status", "error_code", "error_message", "updated_at"])

    try:
        if attachment.provider != "bale":
            raise RuntimeError(f"Unsupported attachment provider: {attachment.provider}")
        if not settings.BALE_BOT_TOKEN:
            raise RuntimeError("BALE_BOT_TOKEN is required to fetch Bale attachments")

        provider = BaleProvider(settings.BALE_BOT_TOKEN)
        file_info = async_to_sync(provider.get_file)(attachment.external_file_id)
        file_path = file_info.get("file_path") or ""
        if not file_path:
            raise RuntimeError("Bale getFile returned no file_path")

        reported_size = file_info.get("file_size") or attachment.declared_size
        if reported_size and int(reported_size) > settings.MAX_PROVIDER_FILE_BYTES:
            raise BaleFileTooLargeError(
                f"Attachment exceeds limit: {reported_size} > {settings.MAX_PROVIDER_FILE_BYTES}"
            )

        content = async_to_sync(provider._require_client().download_file)(
            file_path,
            settings.MAX_PROVIDER_FILE_BYTES,
        )
        storage_key, digest = store_private_bytes(
            attachment_id=str(attachment.id),
            filename=attachment.original_name or f"{attachment.id}.bin",
            content=content,
        )

        with transaction.atomic():
            attachment = CaseAttachment.objects.select_for_update().get(pk=attachment.pk)
            attachment.provider_file_path = file_path
            attachment.storage_key = storage_key
            attachment.sha256 = digest
            attachment.actual_size = len(content)
            attachment.status = CaseAttachment.Status.STORED
            attachment.error_code = ""
            attachment.error_message = ""
            attachment.save()

            job = ProcessingJob.objects.select_for_update().get(pk=job.pk)
            job.status = ProcessingJob.Status.SUCCEEDED
            job.finished_at = timezone.now()
            job.last_error = ""
            job.save(update_fields=["status", "finished_at", "last_error", "updated_at"])

            attempt = ProcessingAttempt.objects.select_for_update().get(pk=attempt.pk)
            attempt.succeeded = True
            attempt.finished_at = timezone.now()
            attempt.metadata = {"bytes": len(content), "sha256": digest}
            attempt.save(update_fields=["succeeded", "finished_at", "metadata"])

            next_job = None
            next_type = _next_job_type(attachment.message.message_type)
            if next_type:
                next_job, _ = ProcessingJob.objects.get_or_create(
                    attachment=attachment,
                    job_type=next_type,
                    defaults={"status": ProcessingJob.Status.PENDING},
                )
                if next_job.status == ProcessingJob.Status.PENDING:
                    transaction.on_commit(lambda next_job=next_job: _enqueue_next_job(next_job))

    except BaleFileTooLargeError as exc:
        with transaction.atomic():
            attachment = CaseAttachment.objects.select_for_update().get(pk=attachment.pk)
            attachment.status = CaseAttachment.Status.REJECTED
            attachment.error_code = "file_too_large"
            attachment.error_message = str(exc)[:2000]
            attachment.save(update_fields=["status", "error_code", "error_message", "updated_at"])

            job = ProcessingJob.objects.select_for_update().get(pk=job.pk)
            job.status = ProcessingJob.Status.FAILED
            job.finished_at = timezone.now()
            job.last_error = str(exc)[:2000]
            job.save(update_fields=["status", "finished_at", "last_error", "updated_at"])

            attempt = ProcessingAttempt.objects.select_for_update().get(pk=attempt.pk)
            attempt.finished_at = timezone.now()
            attempt.error_class = exc.__class__.__name__
            attempt.error_message = str(exc)[:2000]
            attempt.save(update_fields=["finished_at", "error_class", "error_message"])
        return
    except Exception as exc:
        with transaction.atomic():
            attachment = CaseAttachment.objects.select_for_update().get(pk=attachment.pk)
            attachment.status = CaseAttachment.Status.FAILED
            attachment.error_code = "fetch_failed"
            attachment.error_message = str(exc)[:2000]
            attachment.save(update_fields=["status", "error_code", "error_message", "updated_at"])

            job = ProcessingJob.objects.select_for_update().get(pk=job.pk)
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

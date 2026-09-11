from asgiref.sync import async_to_sync
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pathlib import Path

from apps.evidence.services import replace_document_page_evidence, replace_image_analysis_evidence
from apps.messaging.models import CaseMessage
from apps.messaging.providers.bale import BaleProvider
from apps.messaging.providers.bale.client import BaleFileTooLargeError
from apps.system.integrations import get_bale_config

from .document_intelligence import (
    analyze_image_bytes,
    classify_document_text,
    extract_document_pages,
)
from .models import CaseAttachment, ProcessingAttempt, ProcessingJob
from .storage import read_private_bytes, store_private_bytes


IMAGE_FILE_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"
}


def _is_image_attachment(
    message_type: str,
    mime_type: str | None = None,
    filename: str | None = None,
) -> bool:
    if message_type == CaseMessage.MessageType.IMAGE:
        return True
    normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    return normalized_mime.startswith("image/") or (
        Path(filename or "").suffix.lower() in IMAGE_FILE_SUFFIXES
    )


def _next_job_type(
    message_type: str,
    mime_type: str | None = None,
    filename: str | None = None,
) -> str | None:
    if message_type in {CaseMessage.MessageType.VOICE, CaseMessage.MessageType.AUDIO}:
        return ProcessingJob.JobType.TRANSCRIBE_AUDIO
    if _is_image_attachment(message_type, mime_type, filename):
        return ProcessingJob.JobType.ANALYZE_IMAGE
    if message_type == CaseMessage.MessageType.DOCUMENT:
        return ProcessingJob.JobType.EXTRACT_DOCUMENT
    return None


def _enqueue_next_job(job: ProcessingJob) -> None:
    if job.job_type == ProcessingJob.JobType.TRANSCRIBE_AUDIO:
        from apps.transcription.tasks import transcribe_audio

        transcribe_audio.delay(str(job.id))
    elif job.job_type == ProcessingJob.JobType.EXTRACT_DOCUMENT:
        extract_document.delay(str(job.id))
    elif job.job_type == ProcessingJob.JobType.ANALYZE_IMAGE:
        analyze_image.delay(str(job.id))


def _resume_case_extraction(case_id: str) -> None:
    from apps.intelligence.models import ExtractionRun
    from apps.intelligence.tasks import extract_case_facts

    pending = ProcessingJob.objects.filter(
        attachment__message__case_id=case_id,
        job_type__in=[
            ProcessingJob.JobType.FETCH_ATTACHMENT,
            ProcessingJob.JobType.TRANSCRIBE_AUDIO,
            ProcessingJob.JobType.EXTRACT_DOCUMENT,
            ProcessingJob.JobType.ANALYZE_IMAGE,
        ],
        status__in=[ProcessingJob.Status.PENDING, ProcessingJob.Status.RUNNING],
    ).exists()
    if pending:
        return

    run = (
        ExtractionRun.objects.filter(case_id=case_id, status=ExtractionRun.Status.PENDING)
        .order_by("-created_at")
        .first()
    )
    if run is not None:
        extract_case_facts.delay(str(run.id))


def _begin_content_job(job_id: str, expected_type: str) -> tuple[ProcessingJob, ProcessingAttempt]:
    with transaction.atomic():
        # Lock only the ProcessingJob row. CaseMessage.case is nullable, so joining
        # through attachment.message.case would make PostgreSQL apply FOR UPDATE
        # to the nullable side of an outer join.
        job = ProcessingJob.objects.select_for_update().get(pk=job_id)
        if job.status == ProcessingJob.Status.SUCCEEDED:
            return job, None
        if job.job_type != expected_type:
            raise RuntimeError(f"Expected {expected_type}, got {job.job_type}")
        if job.attachment.status != CaseAttachment.Status.STORED or not job.attachment.storage_key:
            raise RuntimeError("Attachment is not stored yet")
        job.status = ProcessingJob.Status.RUNNING
        job.started_at = timezone.now()
        job.attempts += 1
        job.last_error = ""
        job.save(update_fields=["status", "started_at", "attempts", "last_error", "updated_at"])
        attempt = ProcessingAttempt.objects.create(job=job, attempt_number=job.attempts)
        return job, attempt


def _complete_content_job(*, job: ProcessingJob, attempt: ProcessingAttempt, metadata: dict) -> None:
    with transaction.atomic():
        locked_job = ProcessingJob.objects.select_for_update().get(pk=job.pk)
        locked_job.status = ProcessingJob.Status.SUCCEEDED
        locked_job.finished_at = timezone.now()
        locked_job.last_error = ""
        locked_job.save(update_fields=["status", "finished_at", "last_error", "updated_at"])
        locked_attempt = ProcessingAttempt.objects.select_for_update().get(pk=attempt.pk)
        locked_attempt.succeeded = True
        locked_attempt.finished_at = timezone.now()
        locked_attempt.metadata = metadata
        locked_attempt.save(update_fields=["succeeded", "finished_at", "metadata"])

        case_id = locked_job.attachment.message.case_id
        if case_id:
            transaction.on_commit(lambda case_id=str(case_id): _resume_case_extraction(case_id))


def _fail_content_job(*, job: ProcessingJob, attempt: ProcessingAttempt, exc: Exception) -> None:
    with transaction.atomic():
        locked_job = ProcessingJob.objects.select_for_update().get(pk=job.pk)
        locked_job.status = ProcessingJob.Status.FAILED
        locked_job.finished_at = timezone.now()
        locked_job.last_error = str(exc)[:2000]
        locked_job.save(update_fields=["status", "finished_at", "last_error", "updated_at"])
        locked_attempt = ProcessingAttempt.objects.select_for_update().get(pk=attempt.pk)
        locked_attempt.finished_at = timezone.now()
        locked_attempt.error_class = exc.__class__.__name__
        locked_attempt.error_message = str(exc)[:2000]
        locked_attempt.save(update_fields=["finished_at", "error_class", "error_message"])


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def extract_document(self, job_id: str) -> None:
    job, attempt = _begin_content_job(job_id, ProcessingJob.JobType.EXTRACT_DOCUMENT)
    if attempt is None:
        return
    try:
        attachment = job.attachment
        content = read_private_bytes(attachment.storage_key)
        pages = extract_document_pages(
            content,
            mime_type=attachment.mime_type,
            filename=attachment.original_name,
        )
        combined_text = "\n".join(str(page.get("text") or "") for page in pages)
        document_type = classify_document_text(combined_text, attachment.original_name)
        for page in pages:
            if not page.get("document_type") or page.get("document_type") == "document":
                page["document_type"] = document_type
        evidence_count = replace_document_page_evidence(attachment=attachment, pages=pages)
        _complete_content_job(
            job=job,
            attempt=attempt,
            metadata={
                "pages": len(pages),
                "evidence_count": evidence_count,
                "document_type": document_type,
            },
        )
    except Exception as exc:
        _fail_content_job(job=job, attempt=attempt, exc=exc)
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def analyze_image(self, job_id: str) -> None:
    job, attempt = _begin_content_job(job_id, ProcessingJob.JobType.ANALYZE_IMAGE)
    if attempt is None:
        return
    try:
        attachment = job.attachment
        content = read_private_bytes(attachment.storage_key)
        result = analyze_image_bytes(
            content,
            mime_type=attachment.mime_type or "image/jpeg",
            context=attachment.original_name,
        )
        evidence_count = replace_image_analysis_evidence(attachment=attachment, result=result)
        _complete_content_job(
            job=job,
            attempt=attempt,
            metadata={
                "evidence_count": evidence_count,
                "document_type": result.get("document_type") or "image",
                "uncertainty_notes": result.get("uncertainty_notes") or [],
            },
        )
    except Exception as exc:
        _fail_content_job(job=job, attempt=attempt, exc=exc)
        raise


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
        bale = get_bale_config()
        if not bale.enabled or not bale.bot_token:
            raise RuntimeError("Bale Bot Token is required to fetch Bale attachments")

        provider = BaleProvider(bale.bot_token)
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

            next_type = _next_job_type(
                attachment.message.message_type,
                attachment.mime_type,
                attachment.original_name,
            )
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

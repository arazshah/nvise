from django.db import transaction

from .models import CaseAttachment, ProcessingJob


@transaction.atomic
def ensure_attachment_job(*, message, normalized_file) -> CaseAttachment:
    attachment, created = CaseAttachment.objects.get_or_create(
        message=message,
        defaults={
            "provider": message.provider,
            "external_file_id": normalized_file.file_id,
            "original_name": normalized_file.file_name or "",
            "mime_type": normalized_file.mime_type or "",
            "declared_size": normalized_file.file_size,
        },
    )

    if created:
        ProcessingJob.objects.create(
            attachment=attachment,
            job_type=ProcessingJob.JobType.FETCH_ATTACHMENT,
        )

    return attachment

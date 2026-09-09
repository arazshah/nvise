from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.processing.storage import store_private_bytes

from .models import GeneratedDocument
from .renderer import render_revision_docx


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def render_docx(self, document_id: str) -> None:
    with transaction.atomic():
        document = (
            GeneratedDocument.objects.select_for_update()
            .select_related("revision__report__case")
            .get(pk=document_id)
        )
        if document.status == GeneratedDocument.Status.READY:
            return
        document.status = GeneratedDocument.Status.RENDERING
        document.error_message = ""
        document.save(update_fields=["status", "error_message", "updated_at"])

    try:
        content = render_revision_docx(document.revision)
        case = document.revision.report.case
        filename = f"{case.case_code}-report-v{document.revision.revision_number}.docx"
        storage_key, digest = store_private_bytes(
            attachment_id=f"documents/{document.id}",
            filename=filename,
            content=content,
        )
        with transaction.atomic():
            document = GeneratedDocument.objects.select_for_update().get(pk=document.pk)
            document.status = GeneratedDocument.Status.READY
            document.storage_key = storage_key
            document.sha256 = digest
            document.filename = filename
            document.size_bytes = len(content)
            document.completed_at = timezone.now()
            document.save(
                update_fields=[
                    "status",
                    "storage_key",
                    "sha256",
                    "filename",
                    "size_bytes",
                    "completed_at",
                    "updated_at",
                ]
            )
    except Exception as exc:
        with transaction.atomic():
            document = GeneratedDocument.objects.select_for_update().get(pk=document.pk)
            document.status = GeneratedDocument.Status.FAILED
            document.error_message = str(exc)[:2000]
            document.completed_at = timezone.now()
            document.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        raise

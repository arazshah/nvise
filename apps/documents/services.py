from django.db import transaction

from apps.reports.models import ReportRevision

from .models import GeneratedDocument


@transaction.atomic
def ensure_docx_document(*, revision: ReportRevision, requested_by=None) -> GeneratedDocument:
    document, created = GeneratedDocument.objects.get_or_create(
        revision=revision,
        kind=GeneratedDocument.Kind.DOCX,
        defaults={"requested_by": requested_by},
    )
    if not created and document.status == GeneratedDocument.Status.FAILED:
        document.status = GeneratedDocument.Status.PENDING
        document.error_message = ""
        document.requested_by = requested_by or document.requested_by
        document.save(update_fields=["status", "error_message", "requested_by", "updated_at"])
    if document.status == GeneratedDocument.Status.PENDING:
        from .tasks import render_docx

        transaction.on_commit(lambda: render_docx.delay(str(document.id)))
    return document

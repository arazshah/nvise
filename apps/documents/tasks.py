from asgiref.sync import async_to_sync
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.messaging.models import ConversationState
from apps.messaging.providers.bale import BaleProvider
from apps.processing.storage import read_private_bytes, store_private_bytes
from apps.subscriptions.models import UsageRecord
from apps.subscriptions.services import record_usage
from apps.system.integrations import get_bale_config

from .models import GeneratedDocument
from .renderer import render_revision_docx


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def deliver_docx_to_bale(self, document_id: str) -> None:
    document = GeneratedDocument.objects.select_related("revision__report__case").get(pk=document_id)
    if document.status != GeneratedDocument.Status.READY or not document.storage_key:
        return
    case = document.revision.report.case
    state = (
        ConversationState.objects.filter(active_case=case, provider="bale")
        .order_by("-updated_at")
        .first()
    )
    config = get_bale_config()
    if state is None or not config.enabled or not config.bot_token:
        return
    content = read_private_bytes(document.storage_key)
    provider = BaleProvider(config.bot_token)
    async_to_sync(provider.send_document)(
        state.external_chat_id,
        content,
        document.filename or f"{case.case_code}.docx",
        "نسخه تأییدشده گزارش پرونده نویسه",
    )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def render_docx(self, document_id: str) -> None:
    with transaction.atomic():
        document = (
            GeneratedDocument.objects.select_for_update()
            .select_related("revision__report__case__tenant")
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
            record_usage(
                tenant=case.tenant,
                metric=UsageRecord.Metric.DOCUMENT_GENERATED,
                quantity=1,
                idempotency_key=f"document:{document.id}:generated",
                case=case,
                metadata={"revision": document.revision.revision_number, "kind": document.kind},
            )
            transaction.on_commit(lambda: deliver_docx_to_bale.delay(str(document.id)))
    except Exception as exc:
        with transaction.atomic():
            document = GeneratedDocument.objects.select_for_update().get(pk=document.pk)
            document.status = GeneratedDocument.Status.FAILED
            document.error_message = str(exc)[:2000]
            document.completed_at = timezone.now()
            document.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        raise

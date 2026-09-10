from django.db import transaction

from apps.messaging.models import CaseMessage
from apps.transcription.models import Transcript

from .models import Evidence


@transaction.atomic
def sync_message_evidence(message: CaseMessage) -> Evidence | None:
    if message.case_id is None or not message.text.strip():
        return None
    evidence, _ = Evidence.objects.update_or_create(
        case=message.case,
        source_kind=Evidence.SourceKind.MESSAGE,
        message=message,
        transcript_segment=None,
        defaults={"text": message.text.strip(), "metadata": {"message_type": message.message_type}},
    )
    return evidence


@transaction.atomic
def sync_transcript_evidence(transcript: Transcript) -> int:
    if transcript.recording.attachment.message.case_id is None:
        return 0
    case = transcript.recording.attachment.message.case
    created = 0
    for segment in transcript.segments.all():
        _, was_created = Evidence.objects.update_or_create(
            case=case,
            source_kind=Evidence.SourceKind.TRANSCRIPT_SEGMENT,
            message=None,
            transcript_segment=segment,
            defaults={
                "text": segment.text,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "metadata": {"confidence": segment.confidence, "speaker": segment.speaker},
            },
        )
        created += int(was_created)
    return created


@transaction.atomic
def replace_document_page_evidence(*, attachment, pages: list[dict]) -> int:
    message = attachment.message
    if message.case_id is None:
        return 0
    Evidence.objects.filter(
        case=message.case,
        source_kind=Evidence.SourceKind.DOCUMENT_PAGE,
        message=message,
    ).delete()
    created = 0
    for page in pages:
        text = str(page.get("text") or "").strip()
        if not text:
            continue
        metadata = {
            "attachment_id": str(attachment.id),
            "filename": attachment.original_name,
            "mime_type": attachment.mime_type,
            "page": page.get("page"),
            "processing_method": page.get("method") or "document",
            "document_type": page.get("document_type") or "document",
            "uncertainty_notes": page.get("uncertainty_notes") or [],
        }
        Evidence.objects.create(
            case=message.case,
            source_kind=Evidence.SourceKind.DOCUMENT_PAGE,
            message=message,
            transcript_segment=None,
            text=text,
            metadata=metadata,
        )
        created += 1
    return created


@transaction.atomic
def replace_image_analysis_evidence(*, attachment, result: dict) -> int:
    message = attachment.message
    if message.case_id is None:
        return 0
    Evidence.objects.filter(
        case=message.case,
        source_kind=Evidence.SourceKind.IMAGE_ANALYSIS,
        message=message,
    ).delete()

    extracted_text = str(result.get("extracted_text") or "").strip()
    observations = [str(item).strip() for item in result.get("visual_observations") or [] if str(item).strip()]
    body = extracted_text
    if observations:
        rendered = "\n".join(f"مشاهده بصری: {item}" for item in observations)
        body = "\n".join(part for part in [body, rendered] if part).strip()
    if not body:
        return 0

    Evidence.objects.create(
        case=message.case,
        source_kind=Evidence.SourceKind.IMAGE_ANALYSIS,
        message=message,
        transcript_segment=None,
        text=body,
        metadata={
            "attachment_id": str(attachment.id),
            "filename": attachment.original_name,
            "mime_type": attachment.mime_type,
            "document_type": result.get("document_type") or "image",
            "processing_method": "vision",
            "uncertainty_notes": result.get("uncertainty_notes") or [],
        },
    )
    return 1

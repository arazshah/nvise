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

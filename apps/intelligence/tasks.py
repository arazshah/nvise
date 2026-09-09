from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.cases.models import Case
from apps.cases.services import transition_case
from apps.messaging.models import CaseMessage
from apps.processing.models import ProcessingJob
from apps.reports.services import generate_report_revision

from .followups import ensure_follow_up_questions, send_next_follow_up
from .models import CaseFieldIssue, ExtractionRun, FieldSchema
from .providers import get_extraction_provider
from .services import apply_extraction_response, collect_case_evidence, serialize_schema


def _audio_pipeline_pending(case: Case) -> bool:
    return ProcessingJob.objects.filter(
        attachment__message__case=case,
        attachment__message__message_type__in=[
            CaseMessage.MessageType.VOICE,
            CaseMessage.MessageType.AUDIO,
        ],
        job_type__in=[
            ProcessingJob.JobType.FETCH_ATTACHMENT,
            ProcessingJob.JobType.TRANSCRIBE_AUDIO,
        ],
        status__in=[ProcessingJob.Status.PENDING, ProcessingJob.Status.RUNNING],
    ).exists()


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def dispatch_follow_up(self, case_id: str) -> None:
    case = Case.objects.get(pk=case_id)
    send_next_follow_up(case)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def extract_case_facts(self, run_id: str) -> None:
    with transaction.atomic():
        run = (
            ExtractionRun.objects.select_for_update()
            .select_related("case", "schema__sub_vertical__vertical")
            .get(pk=run_id)
        )
        if run.status == ExtractionRun.Status.COMPLETED:
            return
        if _audio_pipeline_pending(run.case):
            raise RuntimeError("Audio evidence is still being processed")
        run.status = ExtractionRun.Status.RUNNING
        run.error_message = ""
        run.save(update_fields=["status", "error_message"])

    try:
        schema = FieldSchema.objects.prefetch_related("fields").select_related(
            "sub_vertical__vertical"
        ).get(pk=run.schema_id)
        evidence = collect_case_evidence(run.case)
        provider = get_extraction_provider()
        payload = provider.extract(schema=serialize_schema(schema), evidence=evidence)

        with transaction.atomic():
            run = ExtractionRun.objects.select_for_update().get(pk=run.pk)
            run.provider = provider.key
            run.model_name = str(payload.get("model") or "")[:128]
            run.input_snapshot = {
                "schema_id": str(schema.id),
                "schema_version": schema.version,
                "evidence_ids": [row["evidence_id"] for row in evidence],
            }
            run.save(update_fields=["provider", "model_name", "input_snapshot"])
            apply_extraction_response(run=run, response=payload)

        has_open_issues = CaseFieldIssue.objects.filter(
            case=run.case,
            status=CaseFieldIssue.Status.OPEN,
        ).exists()
        target = Case.Status.NEEDS_INFORMATION if has_open_issues else Case.Status.READY_FOR_REVIEW
        refreshed_case = Case.objects.get(pk=run.case_id)
        if refreshed_case.status == Case.Status.FINALIZING:
            refreshed_case = transition_case(case=refreshed_case, target_status=target)

        if has_open_issues:
            ensure_follow_up_questions(refreshed_case)
            transaction.on_commit(lambda: dispatch_follow_up.delay(str(refreshed_case.id)))
        elif refreshed_case.status == Case.Status.READY_FOR_REVIEW:
            generate_report_revision(case=refreshed_case, created_by=refreshed_case.created_by)
            from apps.portal.tasks import send_review_link

            transaction.on_commit(lambda: send_review_link.delay(str(refreshed_case.id)))
    except Exception as exc:
        with transaction.atomic():
            run = ExtractionRun.objects.select_for_update().get(pk=run.pk)
            run.status = ExtractionRun.Status.FAILED
            run.error_message = str(exc)[:2000]
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_message", "completed_at"])
        raise

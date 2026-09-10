from asgiref.sync import async_to_sync
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.cases.models import Case
from apps.cases.services import transition_case
from apps.messaging.models import ConversationState
from apps.messaging.providers.bale import BaleProvider
from apps.processing.models import ProcessingJob
from apps.subscriptions.models import UsageRecord
from apps.subscriptions.services import QuotaExceededError, assert_quota, record_usage
from apps.system.integrations import get_bale_config

from .followups import ensure_follow_up_questions, send_next_follow_up
from .models import CaseFieldIssue, ExtractionRun, FieldSchema
from .playbooks import serialize_playbook
from .providers import get_extraction_provider
from .results import analysis_result_keyboard, analysis_result_text
from .services import apply_extraction_response, collect_case_evidence, serialize_schema


CONTENT_JOB_TYPES = [
    ProcessingJob.JobType.FETCH_ATTACHMENT,
    ProcessingJob.JobType.TRANSCRIBE_AUDIO,
    ProcessingJob.JobType.EXTRACT_DOCUMENT,
    ProcessingJob.JobType.ANALYZE_IMAGE,
]


def _case_evidence_pipeline_pending(case: Case) -> bool:
    return ProcessingJob.objects.filter(
        attachment__message__case=case,
        job_type__in=CONTENT_JOB_TYPES,
        status__in=[ProcessingJob.Status.PENDING, ProcessingJob.Status.RUNNING],
    ).exists()


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def dispatch_follow_up(self, case_id: str) -> None:
    case = Case.objects.get(pk=case_id)
    send_next_follow_up(case)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def notify_analysis_result(self, case_id: str) -> None:
    case = Case.objects.get(pk=case_id)
    state = (
        ConversationState.objects.filter(active_case=case, provider="bale")
        .order_by("-updated_at")
        .first()
    )
    bale = get_bale_config()
    if state is None or not bale.enabled or not bale.bot_token:
        return
    provider = BaleProvider(bale.bot_token)
    async_to_sync(provider.send_text)(
        state.external_chat_id,
        analysis_result_text(case),
        analysis_result_keyboard(case),
    )
    state.state = "idle"
    state.pending_action = {"analysis_result_case_id": str(case.id)}
    state.save(update_fields=["state", "pending_action", "updated_at"])


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def extract_case_facts(self, run_id: str) -> None:
    with transaction.atomic():
        run = (
            ExtractionRun.objects.select_for_update()
            .select_related("case__tenant", "case__created_by", "schema__sub_vertical__vertical")
            .get(pk=run_id)
        )
        if run.status == ExtractionRun.Status.COMPLETED:
            return
        if _case_evidence_pipeline_pending(run.case):
            raise RuntimeError("Case evidence is still being processed")
        try:
            assert_quota(run.case.tenant, UsageRecord.Metric.AI_EXTRACTION, 1)
        except QuotaExceededError as exc:
            run.status = ExtractionRun.Status.FAILED
            run.error_message = str(exc)[:2000]
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_message", "completed_at"])
            Case.objects.filter(pk=run.case_id).update(analysis_status=Case.AnalysisStatus.FAILED)
            return
        run.status = ExtractionRun.Status.RUNNING
        run.error_message = ""
        run.save(update_fields=["status", "error_message"])
        Case.objects.filter(pk=run.case_id).update(analysis_status=Case.AnalysisStatus.PROCESSING)

    try:
        schema = FieldSchema.objects.prefetch_related("fields").select_related(
            "sub_vertical__vertical"
        ).get(pk=run.schema_id)
        evidence = collect_case_evidence(run.case)
        playbook = serialize_playbook(run.case)
        provider = get_extraction_provider()
        schema_payload = serialize_schema(schema)
        schema_payload["professional_playbook"] = playbook
        payload = provider.extract(schema=schema_payload, evidence=evidence)

        with transaction.atomic():
            run = ExtractionRun.objects.select_for_update().select_related("case__tenant").get(pk=run.pk)
            run.provider = provider.key
            run.model_name = str(payload.get("model") or "")[:128]
            run.input_snapshot = {
                "schema_id": str(schema.id),
                "schema_version": schema.version,
                "professional_playbook": playbook,
                "evidence_ids": [row["evidence_id"] for row in evidence],
            }
            run.save(update_fields=["provider", "model_name", "input_snapshot"])
            apply_extraction_response(run=run, response=payload)
            record_usage(
                tenant=run.case.tenant,
                metric=UsageRecord.Metric.AI_EXTRACTION,
                quantity=1,
                idempotency_key=f"ai-extraction:{run.id}",
                case=run.case,
                metadata={"provider": provider.key, "model": run.model_name, "playbook": playbook["key"]},
            )

        refreshed_case = Case.objects.get(pk=run.case_id)
        has_open_issues = CaseFieldIssue.objects.filter(
            case=refreshed_case,
            status=CaseFieldIssue.Status.OPEN,
        ).exists()

        if has_open_issues:
            ensure_follow_up_questions(refreshed_case)
            has_open_issues = CaseFieldIssue.objects.filter(
                case=refreshed_case,
                status=CaseFieldIssue.Status.OPEN,
            ).exists()

        refreshed_case.analysis_status = (
            Case.AnalysisStatus.NEEDS_REVIEW if has_open_issues else Case.AnalysisStatus.COMPLETED
        )
        refreshed_case.save(update_fields=["analysis_status", "updated_at"])

        if refreshed_case.status == Case.Status.FINALIZING:
            target = Case.Status.NEEDS_INFORMATION if has_open_issues else Case.Status.OPEN
            refreshed_case = transition_case(case=refreshed_case, target_status=target)

        transaction.on_commit(lambda: notify_analysis_result.delay(str(refreshed_case.id)))
    except Exception as exc:
        with transaction.atomic():
            run = ExtractionRun.objects.select_for_update().get(pk=run.pk)
            run.status = ExtractionRun.Status.FAILED
            run.error_message = str(exc)[:2000]
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_message", "completed_at"])
            Case.objects.filter(pk=run.case_id).update(analysis_status=Case.AnalysisStatus.FAILED)
        raise

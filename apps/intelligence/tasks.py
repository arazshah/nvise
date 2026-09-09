from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import ExtractionRun, FieldSchema
from .providers import get_extraction_provider
from .services import apply_extraction_response, collect_case_evidence, serialize_schema


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
    except Exception as exc:
        with transaction.atomic():
            run = ExtractionRun.objects.select_for_update().get(pk=run.pk)
            run.status = ExtractionRun.Status.FAILED
            run.error_message = str(exc)[:2000]
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_message", "completed_at"])
        raise

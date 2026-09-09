from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from apps.cases.models import Case
from apps.intelligence.models import ExtractionRun
from apps.intelligence.tasks import extract_case_facts
from apps.processing.models import ProcessingJob
from apps.transcription.tasks import transcribe_audio


class Command(BaseCommand):
    help = "Requeue recoverable audio jobs and stalled finalization extraction runs."

    def handle(self, *args, **options):
        requeued_audio = 0
        requeued_extractions = 0

        recoverable_errors = Q(
            last_error__icontains="FOR UPDATE cannot be applied to the nullable side of an outer join"
        ) | Q(last_error__icontains="400 Bad Request") | Q(
            last_error__icontains="AvalAI STT returned HTTP 400"
        )
        failed_jobs = (
            ProcessingJob.objects.filter(
                job_type=ProcessingJob.JobType.TRANSCRIBE_AUDIO,
                status=ProcessingJob.Status.FAILED,
                attachment__storage_key__gt="",
                attachment__message__case__status=Case.Status.FINALIZING,
            )
            .filter(recoverable_errors)
            .select_related("attachment__message__case")
        )

        for job in failed_jobs:
            with transaction.atomic():
                locked = ProcessingJob.objects.select_for_update().get(pk=job.pk)
                if locked.status != ProcessingJob.Status.FAILED:
                    continue
                locked.status = ProcessingJob.Status.PENDING
                locked.finished_at = None
                locked.last_error = ""
                locked.save(update_fields=["status", "finished_at", "last_error", "updated_at"])
                transaction.on_commit(lambda job_id=str(locked.id): transcribe_audio.delay(job_id))
                requeued_audio += 1

        stalled_cases = Case.objects.filter(status=Case.Status.FINALIZING)
        for case in stalled_cases:
            has_pending_audio = ProcessingJob.objects.filter(
                attachment__message__case=case,
                job_type__in=[
                    ProcessingJob.JobType.FETCH_ATTACHMENT,
                    ProcessingJob.JobType.TRANSCRIBE_AUDIO,
                ],
                status__in=[ProcessingJob.Status.PENDING, ProcessingJob.Status.RUNNING],
            ).exists()
            if has_pending_audio:
                continue

            has_failed_audio = ProcessingJob.objects.filter(
                attachment__message__case=case,
                job_type=ProcessingJob.JobType.TRANSCRIBE_AUDIO,
                status=ProcessingJob.Status.FAILED,
            ).exists()
            if has_failed_audio:
                continue

            run = (
                ExtractionRun.objects.filter(
                    case=case,
                    status__in=[ExtractionRun.Status.PENDING, ExtractionRun.Status.FAILED],
                )
                .order_by("-created_at")
                .first()
            )
            if run is not None:
                extract_case_facts.delay(str(run.id))
                requeued_extractions += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Recovery queued: audio={requeued_audio}, extraction={requeued_extractions}"
            )
        )

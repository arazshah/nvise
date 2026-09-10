import pytest

from apps.accounts.models import User
from apps.cases.models import Case
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.models import ExtractionRun
from apps.intelligence.tasks import extract_case_facts
from apps.messaging.models import CaseMessage
from apps.processing.models import CaseAttachment, ProcessingAttempt, ProcessingJob
from apps.processing.tasks import _begin_content_job, _complete_content_job
from apps.tenants.models import Tenant


def _case_with_document_job(*, status=ProcessingJob.Status.PENDING):
    user = User.objects.create_user(username="pipeline-user")
    tenant = Tenant.objects.create(name="Pipeline tenant", slug="pipeline-tenant")
    case = Case.objects.create(
        tenant=tenant,
        created_by=user,
        case_code="PIPE-001",
        title="Pipeline case",
        status=Case.Status.FINALIZING,
        analysis_status=Case.AnalysisStatus.QUEUED,
    )
    message = CaseMessage.objects.create(
        user=user,
        case=case,
        assignment_status=CaseMessage.AssignmentStatus.ASSIGNED,
        provider="bale",
        external_chat_id="pipeline-chat",
        external_message_id="pipeline-document",
        message_type=CaseMessage.MessageType.DOCUMENT,
    )
    attachment = CaseAttachment.objects.create(
        message=message,
        provider="bale",
        external_file_id="file-1",
        original_name="policy.pdf",
        mime_type="application/pdf",
        storage_key="private/policy.pdf",
        status=CaseAttachment.Status.STORED,
    )
    job = ProcessingJob.objects.create(
        attachment=attachment,
        job_type=ProcessingJob.JobType.EXTRACT_DOCUMENT,
        status=status,
    )
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(
        case=case,
        schema=schema,
        provider="pending",
        status=ExtractionRun.Status.PENDING,
    )
    return case, job, run


@pytest.mark.django_db(transaction=True)
def test_begin_content_job_locks_only_processing_job_on_nullable_case_relation():
    _case, job, _run = _case_with_document_job()

    locked_job, attempt = _begin_content_job(str(job.id), ProcessingJob.JobType.EXTRACT_DOCUMENT)

    assert locked_job.status == ProcessingJob.Status.RUNNING
    assert attempt is not None
    assert attempt.job_id == job.id


@pytest.mark.django_db(transaction=True)
def test_extraction_waits_without_failing_when_evidence_pipeline_is_pending():
    case, _job, run = _case_with_document_job()

    extract_case_facts.run(str(run.id))

    run.refresh_from_db()
    case.refresh_from_db()
    assert run.status == ExtractionRun.Status.PENDING
    assert run.error_message == ""
    assert case.analysis_status == Case.AnalysisStatus.QUEUED


@pytest.mark.django_db(transaction=True)
def test_completed_document_job_resumes_pending_extraction(monkeypatch):
    _case, job, run = _case_with_document_job(status=ProcessingJob.Status.RUNNING)
    job.attempts = 1
    job.save(update_fields=["attempts"])
    attempt = ProcessingAttempt.objects.create(job=job, attempt_number=1)
    calls = []
    monkeypatch.setattr(
        "apps.intelligence.tasks.extract_case_facts.delay",
        lambda run_id: calls.append(run_id),
    )

    _complete_content_job(job=job, attempt=attempt, metadata={"evidence_count": 1})

    assert calls == [str(run.id)]

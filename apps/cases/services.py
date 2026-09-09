import uuid

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.subscriptions.models import UsageRecord
from apps.subscriptions.services import assert_quota, record_usage
from apps.tenants.models import Tenant

from .models import Case, CaseEvent


class CaseTransitionError(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Case.Status.DRAFT: {Case.Status.OPEN, Case.Status.CANCELLED},
    Case.Status.OPEN: {Case.Status.FINALIZING, Case.Status.CANCELLED, Case.Status.ARCHIVED},
    Case.Status.FINALIZING: {
        Case.Status.NEEDS_INFORMATION,
        Case.Status.READY_FOR_REVIEW,
        Case.Status.OPEN,
        Case.Status.ARCHIVED,
    },
    Case.Status.NEEDS_INFORMATION: {Case.Status.FINALIZING, Case.Status.OPEN, Case.Status.ARCHIVED},
    Case.Status.READY_FOR_REVIEW: {Case.Status.APPROVED, Case.Status.OPEN, Case.Status.ARCHIVED},
    Case.Status.APPROVED: {Case.Status.ARCHIVED, Case.Status.OPEN},
    Case.Status.ARCHIVED: {Case.Status.OPEN},
    Case.Status.CANCELLED: set(),
}


def generate_case_code() -> str:
    year = timezone.localdate().year
    suffix = uuid.uuid4().hex[:8].upper()
    return f"NVS-{year}-{suffix}"


def _sync_dimensions_for_legacy_status(case: Case, target_status: str) -> list[str]:
    update_fields: list[str] = []

    if target_status == Case.Status.CANCELLED:
        case.lifecycle_status = Case.LifecycleStatus.CANCELLED
        update_fields.append("lifecycle_status")
    elif target_status == Case.Status.ARCHIVED:
        case.lifecycle_status = Case.LifecycleStatus.ARCHIVED
        update_fields.append("lifecycle_status")
    elif target_status == Case.Status.OPEN:
        case.lifecycle_status = Case.LifecycleStatus.ACTIVE
        update_fields.append("lifecycle_status")

    if target_status == Case.Status.FINALIZING:
        case.analysis_status = Case.AnalysisStatus.QUEUED
        update_fields.append("analysis_status")
    elif target_status == Case.Status.NEEDS_INFORMATION:
        case.analysis_status = Case.AnalysisStatus.NEEDS_REVIEW
        update_fields.append("analysis_status")
    elif target_status == Case.Status.READY_FOR_REVIEW:
        case.analysis_status = Case.AnalysisStatus.COMPLETED
        case.report_status = Case.ReportStatus.READY_FOR_REVIEW
        update_fields.extend(["analysis_status", "report_status"])
    elif target_status == Case.Status.APPROVED:
        case.analysis_status = Case.AnalysisStatus.COMPLETED
        case.report_status = Case.ReportStatus.APPROVED
        update_fields.extend(["analysis_status", "report_status"])

    return update_fields


@transaction.atomic
def create_case(*, user, tenant: Tenant, title: str = "") -> Case:
    assert_quota(tenant, UsageRecord.Metric.CASE_CREATED, 1)
    case = Case.objects.create(
        tenant=tenant,
        created_by=user,
        title=title.strip(),
        case_code=generate_case_code(),
        status=Case.Status.OPEN,
        lifecycle_status=Case.LifecycleStatus.ACTIVE,
        analysis_status=Case.AnalysisStatus.NOT_STARTED,
        report_status=Case.ReportStatus.NOT_CREATED,
        opened_at=timezone.now(),
    )
    record_usage(
        tenant=tenant,
        metric=UsageRecord.Metric.CASE_CREATED,
        quantity=1,
        idempotency_key=f"case:{case.id}:created",
        case=case,
    )
    CaseEvent.objects.create(
        case=case,
        event_type="case.created",
        actor=user,
        payload={
            "status": Case.Status.OPEN,
            "lifecycle_status": case.lifecycle_status,
            "analysis_status": case.analysis_status,
            "report_status": case.report_status,
        },
    )
    record_audit_event(
        event_type="case.created",
        tenant=tenant,
        actor=user,
        case=case,
        object_type="case",
        object_id=case.id,
        metadata={"case_code": case.case_code, "status": case.status},
    )
    return case


@transaction.atomic
def transition_case(*, case: Case, target_status: str, actor=None) -> Case:
    """Compatibility transition for legacy callers while workflow dimensions are rolled out."""

    locked = Case.objects.select_for_update().get(pk=case.pk)
    allowed = ALLOWED_TRANSITIONS.get(locked.status, set())
    if target_status not in allowed:
        raise CaseTransitionError(f"Cannot transition case from {locked.status} to {target_status}")

    previous_status = locked.status
    locked.status = target_status
    update_fields = ["status", "updated_at"]
    update_fields.extend(_sync_dimensions_for_legacy_status(locked, target_status))

    now = timezone.now()
    if target_status == Case.Status.OPEN:
        if locked.opened_at is None:
            locked.opened_at = now
            update_fields.append("opened_at")
        if locked.archived_at is not None:
            locked.archived_at = None
            update_fields.append("archived_at")
    elif target_status == Case.Status.FINALIZING:
        locked.finalized_at = now
        update_fields.append("finalized_at")
    elif target_status == Case.Status.APPROVED:
        locked.approved_at = now
        update_fields.append("approved_at")
    elif target_status == Case.Status.ARCHIVED:
        locked.archived_at = now
        update_fields.append("archived_at")

    locked.save(update_fields=list(dict.fromkeys(update_fields)))
    CaseEvent.objects.create(
        case=locked,
        event_type="case.status_changed",
        actor=actor,
        payload={"from": previous_status, "to": target_status},
    )
    record_audit_event(
        event_type="case.status_changed",
        tenant=locked.tenant,
        actor=actor,
        case=locked,
        object_type="case",
        object_id=locked.id,
        metadata={"from": previous_status, "to": target_status},
    )
    return locked


@transaction.atomic
def request_analysis(*, case: Case, actor=None) -> Case:
    """Request analysis without closing the case as a repository."""

    locked = Case.objects.select_for_update().get(pk=case.pk)
    if locked.lifecycle_status != Case.LifecycleStatus.ACTIVE:
        raise CaseTransitionError("Only active cases can be analyzed")
    if locked.analysis_status in {Case.AnalysisStatus.QUEUED, Case.AnalysisStatus.PROCESSING}:
        return locked

    previous = locked.analysis_status
    locked.analysis_status = Case.AnalysisStatus.QUEUED
    locked.status = Case.Status.FINALIZING  # legacy mirror during rollout
    locked.finalized_at = timezone.now()
    locked.save(update_fields=["analysis_status", "status", "finalized_at", "updated_at"])
    CaseEvent.objects.create(
        case=locked,
        event_type="case.analysis_requested",
        actor=actor,
        payload={"from": previous, "to": locked.analysis_status},
    )
    record_audit_event(
        event_type="case.analysis_requested",
        tenant=locked.tenant,
        actor=actor,
        case=locked,
        object_type="case",
        object_id=locked.id,
        metadata={"from": previous, "to": locked.analysis_status},
    )
    return locked


def finish_input(*, case: Case, actor=None) -> Case:
    """Deprecated compatibility alias. New UI should call request_analysis()."""

    return request_analysis(case=case, actor=actor)


@transaction.atomic
def reopen_case(*, case: Case, actor=None) -> Case:
    locked = Case.objects.select_for_update().get(pk=case.pk)
    if locked.lifecycle_status == Case.LifecycleStatus.CANCELLED:
        raise CaseTransitionError("Cancelled cases cannot be reopened")
    locked.lifecycle_status = Case.LifecycleStatus.ACTIVE
    locked.status = Case.Status.OPEN
    locked.archived_at = None
    locked.save(update_fields=["lifecycle_status", "status", "archived_at", "updated_at"])
    CaseEvent.objects.create(case=locked, event_type="case.reopened", actor=actor, payload={})
    return locked


def approve_case(*, case: Case, actor=None) -> Case:
    return transition_case(case=case, target_status=Case.Status.APPROVED, actor=actor)


@transaction.atomic
def archive_case(*, case: Case, actor=None) -> Case:
    """Archive a case regardless of whether it has ever been analyzed."""

    locked = Case.objects.select_for_update().get(pk=case.pk)
    if locked.lifecycle_status == Case.LifecycleStatus.CANCELLED:
        raise CaseTransitionError("Cancelled cases cannot be archived")
    locked.lifecycle_status = Case.LifecycleStatus.ARCHIVED
    locked.status = Case.Status.ARCHIVED  # legacy mirror during rollout
    locked.archived_at = timezone.now()
    locked.save(update_fields=["lifecycle_status", "status", "archived_at", "updated_at"])
    CaseEvent.objects.create(
        case=locked,
        event_type="case.archived",
        actor=actor,
        payload={"analysis_status": locked.analysis_status, "report_status": locked.report_status},
    )
    return locked


def cancel_case(*, case: Case, actor=None) -> Case:
    return transition_case(case=case, target_status=Case.Status.CANCELLED, actor=actor)

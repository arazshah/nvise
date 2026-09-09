import uuid

from django.db import transaction
from django.utils import timezone

from apps.tenants.models import Tenant

from .models import Case, CaseEvent


class CaseTransitionError(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Case.Status.DRAFT: {Case.Status.OPEN, Case.Status.CANCELLED},
    Case.Status.OPEN: {Case.Status.FINALIZING, Case.Status.CANCELLED},
    Case.Status.FINALIZING: {
        Case.Status.NEEDS_INFORMATION,
        Case.Status.READY_FOR_REVIEW,
        Case.Status.OPEN,
    },
    Case.Status.NEEDS_INFORMATION: {Case.Status.FINALIZING, Case.Status.OPEN},
    Case.Status.READY_FOR_REVIEW: {Case.Status.APPROVED, Case.Status.OPEN},
    Case.Status.APPROVED: {Case.Status.ARCHIVED},
    Case.Status.ARCHIVED: set(),
    Case.Status.CANCELLED: set(),
}


def generate_case_code() -> str:
    year = timezone.localdate().year
    suffix = uuid.uuid4().hex[:8].upper()
    return f"NVS-{year}-{suffix}"


@transaction.atomic
def create_case(*, user, tenant: Tenant, title: str = "") -> Case:
    case = Case.objects.create(
        tenant=tenant,
        created_by=user,
        title=title.strip(),
        case_code=generate_case_code(),
        status=Case.Status.OPEN,
        opened_at=timezone.now(),
    )
    CaseEvent.objects.create(
        case=case,
        event_type="case.created",
        actor=user,
        payload={"status": Case.Status.OPEN},
    )
    return case


@transaction.atomic
def transition_case(*, case: Case, target_status: str, actor=None) -> Case:
    locked = Case.objects.select_for_update().get(pk=case.pk)
    allowed = ALLOWED_TRANSITIONS.get(locked.status, set())
    if target_status not in allowed:
        raise CaseTransitionError(f"Cannot transition case from {locked.status} to {target_status}")

    previous_status = locked.status
    locked.status = target_status
    update_fields = ["status", "updated_at"]

    now = timezone.now()
    if target_status == Case.Status.OPEN and locked.opened_at is None:
        locked.opened_at = now
        update_fields.append("opened_at")
    elif target_status == Case.Status.FINALIZING:
        locked.finalized_at = now
        update_fields.append("finalized_at")
    elif target_status == Case.Status.APPROVED:
        locked.approved_at = now
        update_fields.append("approved_at")
    elif target_status == Case.Status.ARCHIVED:
        locked.archived_at = now
        update_fields.append("archived_at")

    locked.save(update_fields=update_fields)
    CaseEvent.objects.create(
        case=locked,
        event_type="case.status_changed",
        actor=actor,
        payload={"from": previous_status, "to": target_status},
    )
    return locked


def finish_input(*, case: Case, actor=None) -> Case:
    return transition_case(case=case, target_status=Case.Status.FINALIZING, actor=actor)


def reopen_case(*, case: Case, actor=None) -> Case:
    return transition_case(case=case, target_status=Case.Status.OPEN, actor=actor)


def approve_case(*, case: Case, actor=None) -> Case:
    return transition_case(case=case, target_status=Case.Status.APPROVED, actor=actor)


def archive_case(*, case: Case, actor=None) -> Case:
    return transition_case(case=case, target_status=Case.Status.ARCHIVED, actor=actor)


def cancel_case(*, case: Case, actor=None) -> Case:
    return transition_case(case=case, target_status=Case.Status.CANCELLED, actor=actor)

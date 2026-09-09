from collections import defaultdict
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.cases.models import Case
from apps.evidence.models import Evidence

from .models import (
    CaseFieldIssue,
    ExtractedFact,
    ExtractionRun,
    FactEvidence,
    FieldDefinition,
    FieldSchema,
)


def serialize_schema(schema: FieldSchema) -> dict[str, Any]:
    return {
        "name": schema.name,
        "version": schema.version,
        "vertical": schema.sub_vertical.vertical.key,
        "sub_vertical": schema.sub_vertical.key,
        "fields": [
            {
                "key": field.key,
                "label": field.label,
                "type": field.value_type,
                "required": field.required,
                "description": field.description,
                "choices": field.choices,
                "hints": field.extraction_hints,
            }
            for field in schema.fields.all()
        ],
    }


def collect_case_evidence(case: Case) -> list[dict[str, Any]]:
    rows = []
    for item in case.evidence_items.order_by("created_at"):
        rows.append(
            {
                "evidence_id": str(item.id),
                "source_kind": item.source_kind,
                "text": item.text,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "metadata": item.metadata,
            }
        )
    return rows


def _value_is_valid(field: FieldDefinition, value: Any) -> bool:
    if value is None:
        return not field.required
    if field.value_type == FieldDefinition.ValueType.TEXT:
        return isinstance(value, str)
    if field.value_type == FieldDefinition.ValueType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if field.value_type == FieldDefinition.ValueType.DECIMAL:
        return isinstance(value, (int, float, str)) and not isinstance(value, bool)
    if field.value_type == FieldDefinition.ValueType.BOOLEAN:
        return isinstance(value, bool)
    if field.value_type in {FieldDefinition.ValueType.DATE, FieldDefinition.ValueType.DATETIME}:
        return isinstance(value, str) and bool(value.strip())
    if field.value_type == FieldDefinition.ValueType.CHOICE:
        return value in field.choices
    return True


def _comparison_value(payload: dict[str, Any]) -> str:
    candidate = payload.get("normalized_value", payload.get("value"))
    return repr(candidate)


@transaction.atomic
def start_extraction(*, case: Case, schema: FieldSchema) -> ExtractionRun:
    run = ExtractionRun.objects.create(
        case=case,
        schema=schema,
        provider="pending",
        status=ExtractionRun.Status.PENDING,
    )
    case.vertical_key = schema.sub_vertical.vertical.key
    case.sub_vertical_key = schema.sub_vertical.key
    case.analysis_status = Case.AnalysisStatus.QUEUED
    case.save(update_fields=["vertical_key", "sub_vertical_key", "analysis_status", "updated_at"])
    from .tasks import extract_case_facts

    transaction.on_commit(lambda: extract_case_facts.delay(str(run.id)))
    return run


def supplemental_questions(case: Case) -> list[str]:
    questions = []
    issues = (
        case.field_issues.filter(status=CaseFieldIssue.Status.OPEN)
        .select_related("field")
        .order_by("field__sequence", "created_at")
    )
    for issue in issues:
        if issue.issue_type == CaseFieldIssue.IssueType.MISSING:
            questions.append(f"لطفاً «{issue.field.label}» را مشخص کنید.")
        elif issue.issue_type == CaseFieldIssue.IssueType.CONFLICT:
            questions.append(f"برای «{issue.field.label}» اطلاعات متناقض ثبت شده؛ لطفاً مقدار صحیح را تأیید کنید.")
        else:
            questions.append(f"لطفاً مقدار معتبر برای «{issue.field.label}» ارائه کنید.")
    return questions


def _upsert_issue(
    *,
    case: Case,
    field: FieldDefinition,
    issue_type: str,
    details: dict[str, Any],
    generated_keys: set[tuple[str, str]],
    terminal_field_ids: set[str],
) -> CaseFieldIssue | None:
    """Create/update an issue without resurrecting a field the user already resolved or waived."""

    field_id = str(field.id)
    if field_id in terminal_field_ids:
        return None

    key = (field_id, issue_type)
    generated_keys.add(key)
    issue = CaseFieldIssue.objects.filter(
        case=case,
        field=field,
        issue_type=issue_type,
        status=CaseFieldIssue.Status.OPEN,
    ).first()
    if issue is None:
        return CaseFieldIssue.objects.create(
            case=case,
            field=field,
            issue_type=issue_type,
            details=details,
        )
    issue.details = details
    issue.save(update_fields=["details"])
    return issue


@transaction.atomic
def apply_extraction_response(*, run: ExtractionRun, response: dict[str, Any]) -> ExtractionRun:
    run = ExtractionRun.objects.select_for_update().select_related("schema", "case").get(pk=run.pk)
    field_map = {field.key: field for field in run.schema.fields.all()}
    evidence_map = {str(item.id): item for item in Evidence.objects.filter(case=run.case)}

    ExtractedFact.objects.filter(extraction_run=run).delete()

    terminal_field_ids = {
        str(field_id)
        for field_id in CaseFieldIssue.objects.filter(
            case=run.case,
            status__in=[
                CaseFieldIssue.Status.RESOLVED,
                CaseFieldIssue.Status.UNAVAILABLE,
                CaseFieldIssue.Status.WAIVED,
            ],
        ).values_list("field_id", flat=True)
    }
    existing_open = list(
        CaseFieldIssue.objects.filter(case=run.case, status=CaseFieldIssue.Status.OPEN)
    )
    generated_keys: set[tuple[str, str]] = set()
    seen_fields: set[str] = set()
    values_by_field: dict[str, set[str]] = defaultdict(set)

    for payload in response.get("facts", []):
        key = payload.get("field")
        field = field_map.get(key)
        if field is None or "value" not in payload:
            continue
        seen_fields.add(key)
        value = payload["value"]
        if not _value_is_valid(field, value):
            _upsert_issue(
                case=run.case,
                field=field,
                issue_type=CaseFieldIssue.IssueType.INVALID,
                details={"value": value, "expected_type": field.value_type},
                generated_keys=generated_keys,
                terminal_field_ids=terminal_field_ids,
            )
            continue

        values_by_field[key].add(_comparison_value(payload))
        fact = ExtractedFact.objects.create(
            case=run.case,
            field=field,
            extraction_run=run,
            value=value,
            normalized_value=payload.get("normalized_value"),
            confidence=payload.get("confidence"),
        )
        for evidence_id in payload.get("evidence_ids", []):
            evidence = evidence_map.get(str(evidence_id))
            if evidence:
                FactEvidence.objects.get_or_create(fact=fact, evidence=evidence)

    for field in run.schema.fields.filter(required=True):
        if field.key not in seen_fields:
            _upsert_issue(
                case=run.case,
                field=field,
                issue_type=CaseFieldIssue.IssueType.MISSING,
                details={"reason": "required_field_not_extracted"},
                generated_keys=generated_keys,
                terminal_field_ids=terminal_field_ids,
            )

    conflict_keys = {key for key, values in values_by_field.items() if len(values) > 1}
    conflict_details: dict[str, dict[str, Any]] = {}
    for conflict in response.get("conflicts", []):
        key = conflict.get("field")
        if key in field_map:
            conflict_keys.add(key)
            conflict_details[key] = conflict

    for key in conflict_keys:
        field = field_map[key]
        _upsert_issue(
            case=run.case,
            field=field,
            issue_type=CaseFieldIssue.IssueType.CONFLICT,
            details=conflict_details.get(key, {"reason": "multiple_distinct_values_extracted"}),
            generated_keys=generated_keys,
            terminal_field_ids=terminal_field_ids,
        )
        ExtractedFact.objects.filter(case=run.case, field=field, extraction_run=run).update(
            status=ExtractedFact.Status.CONFLICTED
        )

    # Open issues that disappeared after re-analysis are resolved instead of being deleted.
    now = timezone.now()
    for issue in existing_open:
        key = (str(issue.field_id), issue.issue_type)
        if key not in generated_keys:
            issue.status = CaseFieldIssue.Status.RESOLVED
            issue.resolved_at = now
            if not issue.resolution_note:
                issue.resolution_note = "در تحلیل مجدد، این ابهام دیگر مشاهده نشد."
            issue.save(update_fields=["status", "resolved_at", "resolution_note"])

    run.raw_response = response
    run.status = ExtractionRun.Status.COMPLETED
    run.completed_at = timezone.now()
    run.error_message = ""
    run.save(update_fields=["raw_response", "status", "completed_at", "error_message"])
    return run

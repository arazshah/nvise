import pytest

from apps.accounts.models import User
from apps.cases.services import create_case
from apps.evidence.models import Evidence
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.followups import ensure_follow_up_questions
from apps.intelligence.models import (
    CaseFieldIssue,
    ExtractedFact,
    ExtractionRun,
    FactEvidence,
)
from apps.intelligence.question_planner import plan_question
from apps.intelligence.services import apply_extraction_response
from apps.messaging.models import CaseMessage
from apps.tenants.models import Tenant, TenantMembership


def _case_and_run(username="planner-v2"):
    user = User.objects.create_user(username=username)
    tenant = Tenant.objects.create(name="Personal", slug=username)
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده تست Planner")
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(
        case=case,
        schema=schema,
        provider="test",
        status=ExtractionRun.Status.COMPLETED,
    )
    return user, case, schema, run


@pytest.mark.django_db
def test_stale_missing_issue_is_resolved_when_fact_exists_in_ledger():
    _, case, schema, run = _case_and_run("planner-stale")
    field = schema.fields.get(key="policy_number")
    ExtractedFact.objects.create(
        case=case,
        field=field,
        extraction_run=run,
        value="1403/311/125/32683/144",
        confidence=0.99,
    )
    issue = CaseFieldIssue.objects.create(
        case=case,
        field=field,
        issue_type=CaseFieldIssue.IssueType.MISSING,
    )

    questions = ensure_follow_up_questions(case)

    issue.refresh_from_db()
    assert questions == []
    assert issue.status == CaseFieldIssue.Status.RESOLVED
    assert "استخراج شده" in issue.resolution_note


@pytest.mark.django_db
def test_conflict_question_explains_candidates_and_document_sources():
    user, case, schema, run = _case_and_run("planner-conflict")
    field = schema.fields.get(key="incident_datetime")
    message = CaseMessage.objects.create(
        user=user,
        case=case,
        assignment_status=CaseMessage.AssignmentStatus.ASSIGNED,
        provider="bale",
        external_chat_id="100",
        external_message_id="200",
        message_type=CaseMessage.MessageType.DOCUMENT,
    )
    evidence = Evidence.objects.create(
        case=case,
        source_kind=Evidence.SourceKind.DOCUMENT_PAGE,
        message=message,
        text="تاریخ حادثه 1404/04/11",
        metadata={"filename": "insurance-policy.pdf", "page": 1},
    )
    first = ExtractedFact.objects.create(
        case=case,
        field=field,
        extraction_run=run,
        value="1404/04/11",
        confidence=0.96,
        status=ExtractedFact.Status.CONFLICTED,
    )
    second = ExtractedFact.objects.create(
        case=case,
        field=field,
        extraction_run=run,
        value="1404/04/12",
        confidence=0.84,
        status=ExtractedFact.Status.CONFLICTED,
    )
    FactEvidence.objects.create(fact=first, evidence=evidence)
    FactEvidence.objects.create(fact=second, evidence=evidence)
    issue = CaseFieldIssue.objects.create(
        case=case,
        field=field,
        issue_type=CaseFieldIssue.IssueType.CONFLICT,
        details={"values": ["1404/04/11", "1404/04/12"]},
    )

    plan = plan_question(issue)

    assert plan.category == "conflict"
    assert plan.should_ask is True
    assert "1404/04/11" in plan.candidates
    assert "1404/04/12" in plan.candidates
    assert any("insurance-policy.pdf" in source for source in plan.sources)
    assert "کدام مقدار" in plan.prompt


@pytest.mark.django_db
def test_noncritical_missing_field_is_suppressed_by_hint():
    _, case, schema, _ = _case_and_run("planner-optional")
    field = schema.fields.get(key="incident_address")
    field.extraction_hints = {"follow_up": "optional"}
    field.save(update_fields=["extraction_hints"])
    issue = CaseFieldIssue.objects.create(
        case=case,
        field=field,
        issue_type=CaseFieldIssue.IssueType.MISSING,
    )

    plan = plan_question(issue)

    assert plan.category == "skip"
    assert plan.should_ask is False
    assert "ضروری نیست" in plan.explanation


@pytest.mark.django_db
def test_extraction_decision_gap_becomes_source_aware_expert_question():
    user, case, schema, run = _case_and_run("planner-expert")
    field = schema.fields.get(key="incident_cause")
    message = CaseMessage.objects.create(
        user=user,
        case=case,
        assignment_status=CaseMessage.AssignmentStatus.ASSIGNED,
        provider="bale",
        external_chat_id="300",
        external_message_id="400",
        message_type=CaseMessage.MessageType.DOCUMENT,
    )
    evidence = Evidence.objects.create(
        case=case,
        source_kind=Evidence.SourceKind.DOCUMENT_PAGE,
        message=message,
        text="در گزارش بازدید به خوردگی بدنه مخزن اشاره شده است.",
        metadata={"filename": "inspection.pdf", "page": 3},
    )

    apply_extraction_response(
        run=run,
        response={
            "facts": [
                {
                    "field": "incident_cause",
                    "value": "خوردگی بدنه مخزن",
                    "confidence": 0.91,
                    "evidence_ids": [str(evidence.id)],
                }
            ],
            "conflicts": [],
            "decision_gaps": [
                {
                    "field": "incident_cause",
                    "rationale": "نوع فنی مخزن برای تفسیر علت و بررسی انطباق با پوشش اهمیت دارد.",
                    "prompt": "آیا بر اساس مشخصات فنی موجود، این مخزن اتمسفریک بوده یا تحت فشار؟",
                    "importance": "high",
                    "evidence_ids": [str(evidence.id)],
                }
            ],
        },
    )

    issue = CaseFieldIssue.objects.get(
        case=case,
        field=field,
        issue_type=CaseFieldIssue.IssueType.EXPERT_JUDGMENT,
    )
    plan = plan_question(issue)

    assert plan.category == "expert_judgment"
    assert plan.should_ask is True
    assert "نوع فنی مخزن" in plan.explanation
    assert "اتمسفریک" in plan.prompt
    assert any("inspection.pdf" in source for source in plan.sources)

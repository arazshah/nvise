import pytest

from apps.accounts.models import User
from apps.cases.services import create_case
from apps.evidence.models import Evidence
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.evaluation import evaluate_golden_case
from apps.intelligence.models import (
    CaseFieldIssue,
    ExtractedFact,
    ExtractionRun,
    FactEvidence,
    FollowUpQuestion,
    GoldenCase,
    GoldenCaseEvaluation,
)
from apps.messaging.models import CaseMessage
from apps.reports.models import Report, ReportClaim, ReportRevision, ReportSection
from apps.tenants.models import Tenant, TenantMembership


def _benchmark_fixture(*, key="golden-fire-loss"):
    user = User.objects.create_user(username=f"user-{key}")
    tenant = Tenant.objects.create(name=key, slug=key)
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده معیار")
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(case=case, schema=schema, provider="test", model_name="golden-test", status=ExtractionRun.Status.COMPLETED)
    return user, case, schema, run


def _add_fact(*, user, case, run, field, value):
    message = CaseMessage.objects.create(
        user=user,
        case=case,
        assignment_status=CaseMessage.AssignmentStatus.ASSIGNED,
        provider="bale",
        external_chat_id="golden-chat",
        external_message_id=f"message-{field.key}",
        message_type=CaseMessage.MessageType.TEXT,
        text=f"{field.label}: {value}",
    )
    evidence = Evidence.objects.create(case=case, source_kind=Evidence.SourceKind.MESSAGE, message=message, text=message.text)
    fact = ExtractedFact.objects.create(
        case=case,
        field=field,
        extraction_run=run,
        value=value,
        normalized_value=value,
        confidence=0.99,
    )
    FactEvidence.objects.create(fact=fact, evidence=evidence, relevance=1.0)
    return fact, evidence


def _add_report(*, case, user, evidence, grounded=True):
    report = Report.objects.create(case=case, status=Report.Status.READY_FOR_REVIEW)
    revision = ReportRevision.objects.create(report=report, revision_number=1, title="گزارش معیار", created_by=user)
    section = ReportSection.objects.create(revision=revision, key="facts", title="یافته‌ها", sequence=0, content="متن")
    ReportClaim.objects.create(
        revision=revision,
        section=section,
        sequence=0,
        claim_type=ReportClaim.ClaimType.FACT,
        text="شماره بیمه‌نامه در پرونده ثبت شده است.",
        fact_keys=["policy_number"],
        evidence_snapshot=[{"evidence_id": str(evidence.id)}] if grounded else [],
    )
    report.current_revision = revision
    report.save(update_fields=["current_revision"])
    return revision


@pytest.mark.django_db
def test_golden_case_passes_when_facts_questions_and_grounding_meet_thresholds():
    user, case, schema, run = _benchmark_fixture()
    _fact, evidence = _add_fact(
        user=user,
        case=case,
        run=run,
        field=schema.fields.get(key="policy_number"),
        value="۱۴۰۳/۳۱۱/۱۲۵/۳۲۶۸۳/۱۴۴",
    )
    revision = _add_report(case=case, user=user, evidence=evidence, grounded=True)
    golden = GoldenCase.objects.create(
        key="insurance-policy-read",
        name="بیمه‌نامه خوانده شده",
        case=case,
        expected_facts={"policy_number": "1403/311/125/32683/144"},
        no_followup_fact_keys=["policy_number"],
        minimum_fact_recall=0.95,
        minimum_grounding_ratio=0.95,
        maximum_redundant_question_rate=0.05,
        expert_report_score=4.5,
    )

    evaluation = evaluate_golden_case(golden, git_sha="abc123")

    assert evaluation.status == GoldenCaseEvaluation.Status.PASSED
    assert evaluation.fact_recall == 1.0
    assert evaluation.exact_fact_accuracy == 1.0
    assert evaluation.redundant_question_rate == 0.0
    assert evaluation.claim_grounding_ratio == 1.0
    assert evaluation.report_revision_id == revision.id
    assert evaluation.git_sha == "abc123"
    assert evaluation.overall_score >= 0.95


@pytest.mark.django_db
def test_golden_case_fails_for_redundant_question_and_ungrounded_claim():
    user, case, schema, run = _benchmark_fixture(key="golden-regression")
    field = schema.fields.get(key="policy_number")
    _fact, evidence = _add_fact(user=user, case=case, run=run, field=field, value="12345")
    _add_report(case=case, user=user, evidence=evidence, grounded=False)
    issue = CaseFieldIssue.objects.create(case=case, field=field, issue_type=CaseFieldIssue.IssueType.MISSING)
    FollowUpQuestion.objects.create(case=case, issue=issue, question_text="شماره بیمه‌نامه چیست؟", status=FollowUpQuestion.Status.ASKED)
    golden = GoldenCase.objects.create(
        key="insurance-no-repeat",
        name="عدم پرسش تکراری",
        case=case,
        expected_facts={"policy_number": "12345"},
        no_followup_fact_keys=["policy_number"],
        minimum_fact_recall=0.95,
        minimum_grounding_ratio=0.90,
        maximum_redundant_question_rate=0.05,
    )

    evaluation = evaluate_golden_case(golden)

    assert evaluation.status == GoldenCaseEvaluation.Status.FAILED
    assert evaluation.fact_recall == 1.0
    assert evaluation.redundant_question_rate == 1.0
    assert evaluation.claim_grounding_ratio == 0.0
    assert evaluation.metrics["gates"]["redundant_question_rate"] is False
    assert evaluation.metrics["gates"]["claim_grounding_ratio"] is False

from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.cases.services import create_case
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.evaluation import evaluate_golden_case
from apps.intelligence.golden_presets import INSURANCE_GOLDEN_KEY
from apps.intelligence.models import CaseFieldIssue, ExtractedFact, ExtractionRun, GoldenCase, GoldenCaseEvaluation
from apps.reports.models import ExpertFactDecision, Report, ReportClaim, ReportRevision, ReportSection
from apps.tenants.models import Tenant, TenantMembership


@pytest.mark.django_db
def test_configure_insurance_golden_case_uses_only_expert_reviewed_facts():
    user = User.objects.create_user(username="golden-insurance-expert")
    tenant = Tenant.objects.create(name="Golden Insurance", slug="golden-insurance")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده خسارت معیار")
    case.vertical_key = "insurance"
    case.sub_vertical_key = "fire_loss"
    case.save(update_fields=["vertical_key", "sub_vertical_key"])
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(case=case, schema=schema, provider="test", status=ExtractionRun.Status.COMPLETED)

    policy_field = schema.fields.get(key="policy_number")
    policy_fact = ExtractedFact.objects.create(
        case=case,
        field=policy_field,
        extraction_run=run,
        value="۱۴۰۳/۳۱۱/۱۲۵/۳۲۶۸۳/۱۴۴",
        normalized_value="۱۴۰۳/۳۱۱/۱۲۵/۳۲۶۸۳/۱۴۴",
        confidence=0.99,
    )
    ExpertFactDecision.objects.create(
        case=case,
        field=policy_field,
        source_fact=policy_fact,
        reviewer=user,
        decision=ExpertFactDecision.Decision.CONFIRMED,
    )

    # This unreviewed fact must not silently become benchmark truth.
    incident_field = schema.fields.get(key="incident_datetime")
    ExtractedFact.objects.create(
        case=case,
        field=incident_field,
        extraction_run=run,
        value="۱۴۰۴/۰۴/۱۱",
        normalized_value="۱۴۰۴/۰۴/۱۱",
        confidence=0.99,
    )

    out = StringIO()
    call_command("configure_insurance_golden_case", case_code=case.case_code, stdout=out)

    golden = GoldenCase.objects.get(key=INSURANCE_GOLDEN_KEY)
    assert golden.case == case
    assert golden.expected_facts == {"policy_number": "۱۴۰۳/۳۱۱/۱۲۵/۳۲۶۸۳/۱۴۴"}
    assert golden.no_followup_fact_keys == ["policy_number"]
    assert "incident_datetime" not in golden.expected_facts
    assert golden.minimum_fact_recall == 0.95
    assert golden.minimum_grounding_ratio == 0.95
    assert golden.minimum_expert_gap_recall == 0.80
    assert golden.report_rubric["criteria"]
    assert "insurance-loss-adjuster-001" in out.getvalue()


@pytest.mark.django_db
def test_golden_case_scores_expected_expert_judgment_recall():
    user = User.objects.create_user(username="golden-gap-expert")
    tenant = Tenant.objects.create(name="Golden Gap", slug="golden-gap")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده معیار gap")
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(case=case, schema=schema, provider="test", status=ExtractionRun.Status.COMPLETED)

    cause_field = schema.fields.get(key="incident_cause")
    ExtractedFact.objects.create(
        case=case,
        field=cause_field,
        extraction_run=run,
        value="خوردگی بدنه مخزن",
        normalized_value="خوردگی بدنه مخزن",
        confidence=0.95,
    )
    CaseFieldIssue.objects.create(
        case=case,
        field=cause_field,
        issue_type=CaseFieldIssue.IssueType.EXPERT_JUDGMENT,
        details={"rationale": "تعیین اثر علت بر تحلیل تخصصی نیازمند نظر کارشناس است."},
    )

    report = Report.objects.create(case=case, status=Report.Status.READY_FOR_REVIEW)
    revision = ReportRevision.objects.create(report=report, revision_number=1, title="گزارش", created_by=user)
    section = ReportSection.objects.create(revision=revision, key="analysis", title="تحلیل", sequence=0, content="متن")
    ReportClaim.objects.create(
        revision=revision,
        section=section,
        sequence=0,
        claim_type=ReportClaim.ClaimType.UNRESOLVED,
        text="نوع دقیق رابطه علت و پوشش نیازمند بررسی کارشناس است.",
        fact_keys=["incident_cause"],
        evidence_snapshot=[],
    )
    report.current_revision = revision
    report.save(update_fields=["current_revision"])

    golden = GoldenCase.objects.create(
        key="insurance-expert-gap",
        name="Expert gap benchmark",
        case=case,
        expected_facts={"incident_cause": "خوردگی بدنه مخزن"},
        expected_expert_judgment_fact_keys=["incident_cause", "estimated_damage_amount"],
        minimum_fact_recall=0.95,
        minimum_expert_gap_recall=0.80,
        minimum_grounding_ratio=0.0,
    )

    evaluation = evaluate_golden_case(golden)

    assert evaluation.expert_gap_recall == 0.5
    assert evaluation.status == GoldenCaseEvaluation.Status.FAILED
    assert evaluation.metrics["expert_gaps"]["missing_fact_keys"] == ["estimated_damage_amount"]
    assert evaluation.metrics["gates"]["expert_gap_recall"] is False

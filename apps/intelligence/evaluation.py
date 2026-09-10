from __future__ import annotations

import os
from typing import Any

from apps.reports.models import ExpertFactDecision, Report, ReportClaim

from .models import ExtractedFact, FollowUpQuestion, GoldenCase, GoldenCaseEvaluation


def _canonical(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "|".join(_canonical(item) for item in value)
    if isinstance(value, dict):
        return "|".join(f"{key}:{_canonical(value[key])}" for key in sorted(value))
    text = str(value).strip().casefold()
    translation = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return " ".join(text.translate(translation).split())


def _authoritative_fact_map(golden_case: GoldenCase) -> tuple[dict[str, Any], Any]:
    case = golden_case.case
    latest_run = case.extraction_runs.filter(status="completed").order_by("-completed_at", "-created_at").first()
    if latest_run is None:
        return {}, None

    decisions = {
        item.field_id: item
        for item in ExpertFactDecision.objects.filter(case=case).select_related("field", "source_fact")
    }
    values: dict[str, Any] = {}
    facts = (
        ExtractedFact.objects.filter(extraction_run=latest_run)
        .exclude(status=ExtractedFact.Status.REJECTED)
        .select_related("field")
        .order_by("field__sequence", "created_at")
    )
    for fact in facts:
        if fact.status == ExtractedFact.Status.CONFLICTED:
            continue
        decision = decisions.get(fact.field_id)
        if decision and decision.decision == ExpertFactDecision.Decision.REJECTED:
            continue
        if decision and decision.decision == ExpertFactDecision.Decision.CORRECTED:
            value = decision.corrected_value
        else:
            value = fact.normalized_value if fact.normalized_value is not None else fact.value
        values[fact.field.key] = value
    return values, latest_run


def _fact_metrics(golden_case: GoldenCase) -> tuple[float, float, dict[str, Any]]:
    expected = golden_case.expected_facts or {}
    actual, latest_run = _authoritative_fact_map(golden_case)
    expected_keys = list(expected)
    found = [key for key in expected_keys if key in actual and _canonical(actual[key]) != ""]
    exact = [key for key in found if _canonical(actual[key]) == _canonical(expected[key])]
    recall = len(found) / len(expected_keys) if expected_keys else 1.0
    accuracy = len(exact) / len(found) if found else (1.0 if not expected_keys else 0.0)
    return recall, accuracy, {
        "expected_count": len(expected_keys),
        "found_count": len(found),
        "exact_count": len(exact),
        "missing_fact_keys": [key for key in expected_keys if key not in found],
        "incorrect_fact_keys": [key for key in found if key not in exact],
        "latest_extraction_run_id": str(latest_run.id) if latest_run else None,
    }


def _question_metrics(golden_case: GoldenCase) -> tuple[float, dict[str, Any]]:
    questions = list(
        FollowUpQuestion.objects.filter(case=golden_case.case)
        .exclude(status=FollowUpQuestion.Status.CANCELLED)
        .select_related("issue__field")
    )
    protected = set(golden_case.no_followup_fact_keys or [])
    redundant = [question for question in questions if question.issue.field.key in protected]
    rate = len(redundant) / len(questions) if questions else 0.0
    return rate, {
        "question_count": len(questions),
        "redundant_question_count": len(redundant),
        "redundant_question_fact_keys": sorted({question.issue.field.key for question in redundant}),
    }


def _grounding_metrics(golden_case: GoldenCase) -> tuple[float, dict[str, Any]]:
    report = Report.objects.filter(case=golden_case.case).select_related("current_revision").first()
    revision = report.current_revision if report else None
    if revision is None:
        return 0.0, {"material_claim_count": 0, "grounded_claim_count": 0, "ungrounded_claim_ids": [], "revision_id": None}

    material_types = [
        ReportClaim.ClaimType.FACT,
        ReportClaim.ClaimType.INFERENCE,
        ReportClaim.ClaimType.PROFESSIONAL_OPINION,
    ]
    claims = list(revision.claims.filter(claim_type__in=material_types))
    grounded = [claim for claim in claims if bool(claim.evidence_snapshot)]
    ratio = len(grounded) / len(claims) if claims else 1.0
    return ratio, {
        "material_claim_count": len(claims),
        "grounded_claim_count": len(grounded),
        "ungrounded_claim_ids": [str(claim.id) for claim in claims if claim not in grounded],
        "revision_id": str(revision.id),
    }


def _overall_score(*, recall: float, accuracy: float, redundant_rate: float, grounding: float, report_score: float | None) -> float:
    components = [
        (recall, 0.35),
        (accuracy, 0.20),
        (1.0 - min(max(redundant_rate, 0.0), 1.0), 0.20),
        (grounding, 0.25),
    ]
    if report_score is not None:
        normalized_report = min(max(report_score / 5.0, 0.0), 1.0)
        components = [(value, weight * 0.90) for value, weight in components]
        components.append((normalized_report, 0.10))
    return round(sum(value * weight for value, weight in components), 4)


def evaluate_golden_case(golden_case: GoldenCase, *, git_sha: str | None = None) -> GoldenCaseEvaluation:
    recall, accuracy, fact_details = _fact_metrics(golden_case)
    redundant_rate, question_details = _question_metrics(golden_case)
    grounding, grounding_details = _grounding_metrics(golden_case)
    report_score = golden_case.expert_report_score
    overall = _overall_score(
        recall=recall,
        accuracy=accuracy,
        redundant_rate=redundant_rate,
        grounding=grounding,
        report_score=report_score,
    )

    gates = {
        "fact_recall": recall >= golden_case.minimum_fact_recall,
        "exact_fact_accuracy": accuracy >= golden_case.minimum_fact_recall,
        "redundant_question_rate": redundant_rate <= golden_case.maximum_redundant_question_rate,
        "claim_grounding_ratio": grounding >= golden_case.minimum_grounding_ratio,
    }
    passed = all(gates.values())
    latest_run_id = fact_details.get("latest_extraction_run_id")
    extraction_run = golden_case.case.extraction_runs.filter(pk=latest_run_id).first() if latest_run_id else None
    return GoldenCaseEvaluation.objects.create(
        golden_case=golden_case,
        extraction_run=extraction_run,
        report_revision_id=grounding_details.get("revision_id"),
        status=GoldenCaseEvaluation.Status.PASSED if passed else GoldenCaseEvaluation.Status.FAILED,
        fact_recall=round(recall, 4),
        exact_fact_accuracy=round(accuracy, 4),
        redundant_question_rate=round(redundant_rate, 4),
        claim_grounding_ratio=round(grounding, 4),
        report_quality_score=report_score,
        overall_score=overall,
        metrics={
            "gates": gates,
            "facts": fact_details,
            "questions": question_details,
            "grounding": grounding_details,
            "thresholds": {
                "minimum_fact_recall": golden_case.minimum_fact_recall,
                "maximum_redundant_question_rate": golden_case.maximum_redundant_question_rate,
                "minimum_grounding_ratio": golden_case.minimum_grounding_ratio,
            },
        },
        git_sha=(git_sha or os.getenv("GITHUB_SHA") or "")[:64],
        model_name=extraction_run.model_name if extraction_run else "",
    )


def evaluate_active_golden_cases(*, git_sha: str | None = None) -> list[GoldenCaseEvaluation]:
    return [
        evaluate_golden_case(golden_case, git_sha=git_sha)
        for golden_case in GoldenCase.objects.filter(is_active=True).select_related("case").order_by("key")
    ]

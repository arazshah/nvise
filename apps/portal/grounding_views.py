from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.cases.models import Case
from apps.reports.models import ExpertFactDecision, Report, ReportClaimReview
from apps.reports.services import generate_report_revision, save_claim_review, save_expert_fact_decision

from .services import user_can_review_case


def _case_for_user(user, case_code: str) -> Case:
    case = get_object_or_404(Case.objects.select_related("tenant", "created_by"), case_code__iexact=case_code)
    if not user_can_review_case(user=user, case=case):
        raise Http404
    return case


def _fact_rows(revision, case):
    decisions = {
        str(item.field_id): item
        for item in ExpertFactDecision.objects.filter(case=case).select_related("field", "source_fact", "reviewer")
    }
    rows = []
    for key, fact in (revision.structured_data.get("facts") or {}).items():
        field_id = str(fact.get("field_id") or "")
        decision = decisions.get(field_id)
        rows.append({"key": key, "fact": fact, "decision": decision})
    return rows


@login_required
@require_GET
def grounding_overview(request, case_code: str):
    case = _case_for_user(request.user, case_code)
    report = Report.objects.filter(case=case).select_related("current_revision").first()
    revision = report.current_revision if report else None
    claim_rows = []
    if revision:
        reviews = {
            str(item.claim_id): item
            for item in ReportClaimReview.objects.filter(
                claim__revision=revision,
                reviewer=request.user,
            ).select_related("claim")
        }
        for claim in revision.claims.select_related("section").order_by("section__sequence", "sequence", "id"):
            claim_rows.append({"claim": claim, "review": reviews.get(str(claim.id))})
    return render(
        request,
        "portal/grounding_review.html",
        {
            "case": case,
            "report": report,
            "revision": revision,
            "fact_rows": _fact_rows(revision, case) if revision else [],
            "claim_rows": claim_rows,
            "report_stale": bool(report and report.status == Report.Status.DRAFT and revision),
        },
    )


@login_required
@require_POST
def fact_decision(request, case_code: str, fact_id):
    case = _case_for_user(request.user, case_code)
    try:
        save_expert_fact_decision(
            case=case,
            user=request.user,
            fact_id=fact_id,
            decision=request.POST.get("decision", ""),
            corrected_value=request.POST.get("corrected_value"),
            note=request.POST.get("note", ""),
        )
    except Exception as exc:
        if isinstance(exc, ValueError) or exc.__class__.__name__ == "DoesNotExist":
            return HttpResponseBadRequest(str(exc))
        raise
    return redirect("portal:grounding-overview", case_code=case.case_code)


@login_required
@require_POST
def claim_decision(request, case_code: str, claim_id):
    case = _case_for_user(request.user, case_code)
    try:
        save_claim_review(
            case=case,
            user=request.user,
            claim_id=claim_id,
            decision=request.POST.get("decision", ""),
            note=request.POST.get("note", ""),
        )
    except Exception as exc:
        if isinstance(exc, ValueError) or exc.__class__.__name__ == "DoesNotExist":
            return HttpResponseBadRequest(str(exc))
        raise
    return redirect("portal:grounding-overview", case_code=case.case_code)


@login_required
@require_POST
def regenerate_grounded_report(request, case_code: str):
    case = _case_for_user(request.user, case_code)
    report = Report.objects.filter(case=case).first()
    if report is None or report.status != Report.Status.DRAFT:
        return HttpResponseBadRequest("این گزارش در حال حاضر نیازمند بازسازی نیست.")
    try:
        generate_report_revision(case=case, created_by=request.user)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    return redirect("portal:case-review", case_code=case.case_code)

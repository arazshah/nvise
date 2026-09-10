from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.cases.models import Case
from apps.cases.services import CaseTransitionError, request_analysis
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.models import CaseFieldIssue
from apps.intelligence.results import analysis_result_summary, waive_open_issues
from apps.intelligence.services import start_extraction
from apps.reports.models import Report
from apps.reports.services import generate_report_revision
from apps.system.models import IntegrationSettings

from .services import user_can_review_case


def _case_for_user(user, case_code: str) -> Case:
    case = get_object_or_404(Case.objects.select_related("tenant"), case_code__iexact=case_code)
    if not user_can_review_case(user=user, case=case):
        raise Http404
    return case


def _issue_reason(issue: CaseFieldIssue) -> str:
    details = issue.details or {}
    if issue.issue_type == CaseFieldIssue.IssueType.MISSING:
        return "این مورد پس از بررسی متن‌ها، صوت‌ها و مدارک پردازش‌شده پرونده پیدا نشده است."
    if issue.issue_type == CaseFieldIssue.IssueType.CONFLICT:
        values = details.get("values") or details.get("candidates") or []
        if values:
            return "مقادیر متفاوت یافت شده: " + "، ".join(str(value) for value in values[:4])
        return "برای این مورد اطلاعات متفاوت یا متناقض یافت شده است."
    if issue.issue_type == CaseFieldIssue.IssueType.EXPERT_JUDGMENT:
        rationale = str(details.get("rationale") or "").strip()
        prompt = str(details.get("prompt") or "").strip()
        if rationale and prompt:
            return f"{rationale} — پرسش تخصصی: {prompt}"
        return rationale or prompt or "این موضوع با شواهد پرونده به‌تنهایی قابل تعیین قطعی نیست و نیازمند نظر تخصصی شماست."
    value = details.get("value")
    if value is not None:
        return f"مقدار «{value}» با قالب مورد انتظار سازگار نیست."
    return "مقدار استخراج‌شده با قالب مورد انتظار سازگار نیست."


@login_required
@require_GET
def analysis_overview(request, case_code: str):
    case = _case_for_user(request.user, case_code)
    summary = analysis_result_summary(case)
    issues = list(
        CaseFieldIssue.objects.filter(case=case, status=CaseFieldIssue.Status.OPEN)
        .select_related("field")
        .order_by("field__sequence", "created_at")
    )
    issue_rows = [
        {
            "issue": issue,
            "reason": _issue_reason(issue),
        }
        for issue in issues
    ]
    integration = IntegrationSettings.objects.filter(pk=1).first()
    report = Report.objects.filter(case=case).select_related("current_revision").first()
    return render(
        request,
        "portal/analysis_overview.html",
        {
            "case": case,
            "summary": summary,
            "issue_rows": issue_rows,
            "bale_public_url": integration.bale_public_url if integration else "",
            "report": report,
        },
    )


@login_required
@require_POST
def start_analysis_view(request, case_code: str):
    case = _case_for_user(request.user, case_code)
    try:
        case = request_analysis(case=case, actor=request.user)
    except CaseTransitionError:
        return HttpResponseBadRequest("این پرونده در وضعیت فعلی قابل تحلیل نیست.")
    schema = ensure_fire_loss_schema()
    start_extraction(case=case, schema=schema)
    return redirect("portal:analysis-overview", case_code=case.case_code)


@login_required
@require_POST
def continue_with_current_view(request, case_code: str):
    case = _case_for_user(request.user, case_code)
    waive_open_issues(case, actor=request.user)
    return redirect("portal:analysis-overview", case_code=case.case_code)


@login_required
@require_POST
def generate_report_view(request, case_code: str):
    case = _case_for_user(request.user, case_code)
    try:
        generate_report_revision(case=case, created_by=request.user)
    except ValueError:
        return HttpResponseBadRequest(
            "هنوز امکان تولید گزارش وجود ندارد. ابتدا تحلیل را کامل کنید یا درباره موارد باز تصمیم بگیرید."
        )
    return redirect("portal:case-review", case_code=case.case_code)

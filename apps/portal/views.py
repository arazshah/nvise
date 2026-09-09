from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.cases.models import Case
from apps.documents.models import GeneratedDocument
from apps.processing.storage import read_private_bytes
from apps.reports.models import Report, ReportRevision
from apps.reports.services import approve_report, create_review_revision

from .models import ReviewAccessToken
from .services import consume_review_access_token, user_can_review_case


def _reviewable_case(user, case_code: str) -> Case:
    case = get_object_or_404(Case.objects.select_related("tenant"), case_code__iexact=case_code)
    if not user_can_review_case(user=user, case=case):
        raise Http404
    return case


@require_http_methods(["GET", "POST"])
def review_access(request, token: str):
    token_row = ReviewAccessToken.objects.filter(token_hash__isnull=False).filter(
        token_hash=__import__("hashlib").sha256(token.encode("utf-8")).hexdigest()
    ).select_related("case").first()
    if request.method == "GET":
        return render(request, "portal/access.html", {"token_row": token_row})

    try:
        consumed = consume_review_access_token(token)
    except (ReviewAccessToken.DoesNotExist, ValueError, PermissionError):
        return HttpResponseBadRequest("این لینک ورود نامعتبر، منقضی یا قبلاً استفاده شده است.")
    login(request, consumed.user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("portal:case-review", case_code=consumed.case.case_code)


@login_required
@require_http_methods(["GET"])
def case_review(request, case_code: str):
    case = _reviewable_case(request.user, case_code)
    report = Report.objects.filter(case=case).select_related("current_revision").first()
    revision = report.current_revision if report else None
    sections = revision.sections.all() if revision else []
    evidence = case.evidence_items.order_by("created_at")
    documents = (
        GeneratedDocument.objects.filter(revision=revision).order_by("-created_at")
        if revision
        else GeneratedDocument.objects.none()
    )
    return render(
        request,
        "portal/case_review.html",
        {
            "case": case,
            "report": report,
            "revision": revision,
            "sections": sections,
            "evidence": evidence,
            "documents": documents,
        },
    )


@login_required
@require_POST
def edit_report(request, case_code: str):
    case = _reviewable_case(request.user, case_code)
    report = get_object_or_404(Report.objects.select_related("current_revision"), case=case)
    revision = report.current_revision
    if revision is None:
        return HttpResponseBadRequest("گزارشی برای ویرایش وجود ندارد.")
    section_contents = {
        section.key: request.POST.get(f"section_{section.key}", section.content)
        for section in revision.sections.all()
    }
    create_review_revision(
        case=case,
        user=request.user,
        title=request.POST.get("title", revision.title),
        summary=request.POST.get("summary", revision.summary),
        section_contents=section_contents,
    )
    return redirect("portal:case-review", case_code=case.case_code)


@login_required
@require_POST
def approve_report_view(request, case_code: str):
    case = _reviewable_case(request.user, case_code)
    approve_report(case=case, user=request.user, note=request.POST.get("note", ""))
    return redirect("portal:case-review", case_code=case.case_code)


@login_required
@require_http_methods(["GET"])
def download_document(request, case_code: str, document_id):
    case = _reviewable_case(request.user, case_code)
    document = get_object_or_404(
        GeneratedDocument.objects.select_related("revision__report"),
        pk=document_id,
        revision__report__case=case,
    )
    if document.status != GeneratedDocument.Status.READY or not document.storage_key:
        raise Http404
    content = read_private_bytes(document.storage_key)
    response = FileResponse(
        __import__("io").BytesIO(content),
        content_type=document.mime_type,
        as_attachment=True,
        filename=document.filename or f"{case.case_code}.docx",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response

from io import BytesIO

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.cases.action_suggestions import accept_action_suggestion, generate_action_suggestions, reject_action_suggestion
from apps.cases.actions import complete_case_action, create_manual_action, next_best_action, open_case_actions, sync_system_actions
from apps.cases.models import Case, CaseAction, CaseActionSuggestion
from apps.cases.services import CaseTransitionError, archive_case, reopen_case
from apps.documents.models import GeneratedDocument
from apps.messaging.models import CaseMessage
from apps.processing.models import CaseAttachment
from apps.processing.storage import read_private_bytes
from apps.reports.models import Report, ReportSectionReview
from apps.reports.services import (
    approve_report,
    create_review_revision,
    review_progress,
    save_section_review,
)

from .models import PortalAccessToken, ReviewAccessToken
from .services import (
    consume_portal_access_token,
    consume_review_access_token,
    get_portal_access_token,
    user_can_review_case,
)


def _accessible_cases(user):
    return Case.objects.filter(
        tenant__memberships__user=user,
        tenant__memberships__is_active=True,
        tenant__is_active=True,
    ).distinct()


def _accessible_case(user, case_code: str) -> Case:
    case = get_object_or_404(Case.objects.select_related("tenant"), case_code__iexact=case_code)
    if not user_can_review_case(user=user, case=case):
        raise Http404
    return case


def _reviewable_case(user, case_code: str) -> Case:
    return _accessible_case(user, case_code)


def login_required_page(request):
    return render(request, "portal/login_required.html")


@require_http_methods(["GET", "POST"])
def portal_access(request, token: str):
    token_row = get_portal_access_token(token)
    now = __import__("django.utils.timezone", fromlist=["now"]).now()
    valid = bool(
        token_row
        and token_row.consumed_at is None
        and token_row.revoked_at is None
        and token_row.expires_at > now
        and token_row.user.is_active
    )

    if request.method == "GET":
        return render(
            request,
            "portal/portal_access.html",
            {"token_row": token_row, "token_valid": valid},
        )

    try:
        consumed = consume_portal_access_token(token)
    except (PortalAccessToken.DoesNotExist, ValueError, PermissionError):
        return HttpResponseBadRequest("این لینک ورود نامعتبر، منقضی یا قبلاً استفاده شده است.")

    login(request, consumed.user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.cycle_key()
    return redirect("portal:dashboard")


@require_http_methods(["GET", "POST"])
def review_access(request, token: str):
    import hashlib

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    token_row = ReviewAccessToken.objects.filter(token_hash=token_hash).select_related("case").first()
    if request.method == "GET":
        return render(request, "portal/access.html", {"token_row": token_row})

    try:
        consumed = consume_review_access_token(token)
    except (ReviewAccessToken.DoesNotExist, ValueError, PermissionError):
        return HttpResponseBadRequest("این لینک ورود نامعتبر، منقضی یا قبلاً استفاده شده است.")
    login(request, consumed.user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.cycle_key()
    return redirect("portal:case-repository", case_code=consumed.case.case_code)


@login_required
@require_http_methods(["GET"])
def dashboard(request):
    cases = _accessible_cases(request.user).annotate(
        open_issue_count=Count(
            "field_issues",
            filter=Q(field_issues__status="open"),
            distinct=True,
        ),
        message_count=Count("messages", distinct=True),
        open_action_count=Count(
            "actions",
            filter=Q(actions__status=CaseAction.Status.OPEN),
            distinct=True,
        ),
    )

    active_count = cases.filter(lifecycle_status=Case.LifecycleStatus.ACTIVE).count()
    archived_count = cases.filter(lifecycle_status=Case.LifecycleStatus.ARCHIVED).count()
    needs_action_count = cases.filter(
        Q(analysis_status__in=[Case.AnalysisStatus.NEEDS_REVIEW, Case.AnalysisStatus.FAILED])
        | Q(report_status=Case.ReportStatus.READY_FOR_REVIEW)
        | Q(open_action_count__gt=0)
    ).count()
    reports_ready_count = cases.filter(
        report_status__in=[Case.ReportStatus.READY_FOR_REVIEW, Case.ReportStatus.APPROVED]
    ).count()

    recent_cases = list(cases.order_by("-updated_at")[:6])
    action_cases = list(
        cases.filter(
            Q(analysis_status__in=[Case.AnalysisStatus.NEEDS_REVIEW, Case.AnalysisStatus.FAILED])
            | Q(report_status=Case.ReportStatus.READY_FOR_REVIEW)
            | Q(open_action_count__gt=0)
        )
        .order_by("-updated_at")[:5]
    )

    for case in recent_cases:
        case.next_action = next_best_action(case)
    for case in action_cases:
        case.next_action = next_best_action(case)

    display_name = getattr(request.user, "display_name", "") or request.user.get_username()
    return render(
        request,
        "portal/dashboard.html",
        {
            "display_name": display_name,
            "total_count": cases.count(),
            "active_count": active_count,
            "archived_count": archived_count,
            "needs_action_count": needs_action_count,
            "reports_ready_count": reports_ready_count,
            "recent_cases": recent_cases,
            "action_cases": action_cases,
        },
    )


@login_required
@require_http_methods(["GET"])
def case_list(request):
    cases = _accessible_cases(request.user).order_by("-updated_at")
    active_cases = [case for case in cases if case.lifecycle_status == Case.LifecycleStatus.ACTIVE]
    archived_cases = [case for case in cases if case.lifecycle_status == Case.LifecycleStatus.ARCHIVED]
    return render(
        request,
        "portal/case_list.html",
        {"active_cases": active_cases, "archived_cases": archived_cases},
    )


def _repository_messages(case: Case, kind: str):
    messages = case.messages.select_related("attachment").order_by("-sent_at", "-received_at")
    if kind == "audio":
        messages = messages.filter(message_type__in=[CaseMessage.MessageType.VOICE, CaseMessage.MessageType.AUDIO])
    elif kind == "image":
        messages = messages.filter(message_type=CaseMessage.MessageType.IMAGE)
    elif kind == "document":
        messages = messages.filter(message_type=CaseMessage.MessageType.DOCUMENT)
    elif kind == "note":
        messages = messages.filter(message_type=CaseMessage.MessageType.TEXT)
    return messages


def _message_rows(messages):
    rows = []
    for message in messages:
        attachment = getattr(message, "attachment", None)
        transcript = None
        if attachment is not None and hasattr(attachment, "recording"):
            transcript = attachment.recording.transcripts.filter(status="completed").order_by("-completed_at", "-created_at").first()
        rows.append({"message": message, "attachment": attachment, "transcript": transcript})
    return rows


@login_required
@require_http_methods(["GET"])
def case_repository(request, case_code: str):
    case = _accessible_case(request.user, case_code)
    kind = request.GET.get("type", "all")
    if kind not in {"all", "audio", "image", "document", "note"}:
        kind = "all"

    counts = {
        "all": case.messages.count(),
        "audio": case.messages.filter(message_type__in=[CaseMessage.MessageType.VOICE, CaseMessage.MessageType.AUDIO]).count(),
        "image": case.messages.filter(message_type=CaseMessage.MessageType.IMAGE).count(),
        "document": case.messages.filter(message_type=CaseMessage.MessageType.DOCUMENT).count(),
        "note": case.messages.filter(message_type=CaseMessage.MessageType.TEXT).count(),
    }
    rows = _message_rows(_repository_messages(case, kind))
    report = Report.objects.filter(case=case).select_related("current_revision").first()
    actions = list(open_case_actions(case)[:20])
    next_action = next_best_action(case)
    suggestions = list(
        case.action_suggestions.filter(status=CaseActionSuggestion.Status.PROPOSED)
        .order_by("-created_at")[:10]
    )
    evidence_by_id = {
        str(item.id): item
        for item in case.evidence_items.filter(
            id__in=[
                evidence_id
                for suggestion in suggestions
                for evidence_id in (suggestion.source_evidence_ids or [])
            ]
        )
    }
    suggestion_rows = [
        {
            "suggestion": suggestion,
            "sources": [
                evidence_by_id[evidence_id]
                for evidence_id in (suggestion.source_evidence_ids or [])
                if evidence_id in evidence_by_id
            ],
        }
        for suggestion in suggestions
    ]
    return render(
        request,
        "portal/case_repository.html",
        {
            "case": case,
            "kind": kind,
            "counts": counts,
            "rows": rows,
            "report": report,
            "case_actions": actions,
            "next_action": next_action,
            "suggestion_rows": suggestion_rows,
        },
    )


@login_required
@require_http_methods(["GET"])
def download_attachment(request, case_code: str, attachment_id):
    case = _accessible_case(request.user, case_code)
    attachment = get_object_or_404(
        CaseAttachment.objects.select_related("message"),
        pk=attachment_id,
        message__case=case,
        status=CaseAttachment.Status.STORED,
    )
    if not attachment.storage_key:
        raise Http404
    content = read_private_bytes(attachment.storage_key)
    response = FileResponse(
        BytesIO(content),
        content_type=attachment.mime_type or "application/octet-stream",
        as_attachment=True,
        filename=attachment.original_name or f"nvise-{attachment.id}",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def archive_case_view(request, case_code: str):
    case = _accessible_case(request.user, case_code)
    try:
        archive_case(case=case, actor=request.user)
    except CaseTransitionError:
        return HttpResponseBadRequest("این پرونده در وضعیت فعلی قابل بایگانی نیست.")
    return redirect("portal:case-repository", case_code=case.case_code)


@login_required
@require_POST
def reopen_case_view(request, case_code: str):
    case = _accessible_case(request.user, case_code)
    try:
        reopen_case(case=case, actor=request.user)
    except CaseTransitionError:
        return HttpResponseBadRequest("این پرونده قابل بازگشایی نیست.")
    return redirect("portal:case-repository", case_code=case.case_code)


def _fact_review_rows(revision, evidence_by_id):
    if revision is None:
        return []
    rows = []
    for key, fact in (revision.structured_data.get("facts") or {}).items():
        sources = []
        for ref in fact.get("evidence") or []:
            item = evidence_by_id.get(str(ref.get("evidence_id")))
            if item is not None:
                sources.append({"evidence": item, "reference": ref})
        rows.append({"key": key, "fact": fact, "sources": sources})
    return rows


@login_required
@require_http_methods(["GET"])
def case_review(request, case_code: str):
    case = _reviewable_case(request.user, case_code)
    report = Report.objects.filter(case=case).select_related("current_revision").first()
    revision = report.current_revision if report else None
    sections = list(revision.sections.all()) if revision else []
    evidence = list(case.evidence_items.order_by("created_at"))
    evidence_by_id = {str(item.id): item for item in evidence}
    reviews = {}
    progress = None
    if revision:
        reviews = {
            str(item.section_id): item
            for item in revision.section_reviews.filter(reviewer=request.user).select_related("section")
        }
        progress = review_progress(revision=revision, user=request.user)
    section_rows = [
        {"section": section, "review": reviews.get(str(section.id))}
        for section in sections
    ]
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
            "section_rows": section_rows,
            "evidence": evidence,
            "fact_rows": _fact_review_rows(revision, evidence_by_id),
            "review_progress": progress,
            "documents": documents,
        },
    )


@login_required
@require_POST
def review_section(request, case_code: str, section_id):
    case = _reviewable_case(request.user, case_code)
    try:
        save_section_review(
            case=case,
            user=request.user,
            section_id=section_id,
            decision=request.POST.get("decision", ""),
            note=request.POST.get("note", ""),
            evidence_ids=request.POST.getlist("evidence_ids"),
        )
    except (ValueError, ReportSectionReview.DoesNotExist):
        return HttpResponseBadRequest("تصمیم بررسی این بخش معتبر نیست یا به نسخه جاری گزارش تعلق ندارد.")
    except Exception as exc:
        if exc.__class__.__name__ == "DoesNotExist":
            return HttpResponseBadRequest("بخش گزارش پیدا نشد یا متعلق به نسخه جاری نیست.")
        raise
    return redirect("portal:case-review", case_code=case.case_code)


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
    try:
        approve_report(case=case, user=request.user, note=request.POST.get("note", ""))
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
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
        BytesIO(content),
        content_type=document.mime_type,
        as_attachment=True,
        filename=document.filename or f"{case.case_code}.docx",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def create_case_action_view(request, case_code: str):
    case = _accessible_case(request.user, case_code)
    due_at = None
    raw_due = request.POST.get("due_at", "").strip()
    if raw_due:
        due_at = parse_datetime(raw_due)
        if due_at is None:
            return HttpResponseBadRequest("زمان یادآوری معتبر نیست.")
        if timezone.is_naive(due_at):
            due_at = timezone.make_aware(due_at, timezone.get_current_timezone())
    try:
        create_manual_action(
            case=case,
            user=request.user,
            title=request.POST.get("title", ""),
            description=request.POST.get("description", ""),
            due_at=due_at,
        )
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    return redirect("portal:case-repository", case_code=case.case_code)


@login_required
@require_POST
def complete_case_action_view(request, case_code: str, action_id):
    case = _accessible_case(request.user, case_code)
    try:
        complete_case_action(case=case, action_id=action_id, user=request.user)
    except (CaseAction.DoesNotExist, ValueError):
        return HttpResponseBadRequest("این اقدام قابل تکمیل نیست.")
    return redirect("portal:case-repository", case_code=case.case_code)


@login_required
@require_http_methods(["GET"])
def today_view(request):
    accessible = _accessible_cases(request.user).filter(lifecycle_status=Case.LifecycleStatus.ACTIVE)
    for case in accessible[:200]:
        sync_system_actions(case)

    now = timezone.now()
    local_today = timezone.localdate()
    tomorrow = local_today + __import__("datetime").timedelta(days=1)
    tomorrow_start = timezone.make_aware(
        __import__("datetime").datetime.combine(tomorrow, __import__("datetime").time.min),
        timezone.get_current_timezone(),
    )
    today_start = timezone.make_aware(
        __import__("datetime").datetime.combine(local_today, __import__("datetime").time.min),
        timezone.get_current_timezone(),
    )
    week_end = tomorrow_start + __import__("datetime").timedelta(days=7)

    actions = CaseAction.objects.filter(
        case__in=accessible,
        status=CaseAction.Status.OPEN,
    ).select_related("case").order_by("-priority", "due_at", "created_at")

    overdue = list(actions.filter(due_at__lt=now))
    today = list(actions.filter(due_at__gte=now, due_at__lt=tomorrow_start))
    important = list(
        actions.filter(
            due_at__isnull=True,
            priority__gte=CaseAction.Priority.HIGH,
        )
    )
    upcoming = list(actions.filter(due_at__gte=tomorrow_start, due_at__lt=week_end))
    unscheduled = list(
        actions.filter(due_at__isnull=True, priority__lt=CaseAction.Priority.HIGH)[:20]
    )

    return render(
        request,
        "portal/today.html",
        {
            "overdue_actions": overdue,
            "today_actions": today,
            "important_actions": important,
            "upcoming_actions": upcoming,
            "unscheduled_actions": unscheduled,
            "today_count": len(overdue) + len(today) + len(important),
            "today_start": today_start,
        },
    )


@login_required
@require_POST
def generate_case_action_suggestions_view(request, case_code: str):
    case = _accessible_case(request.user, case_code)
    try:
        created = generate_action_suggestions(case)
    except Exception:
        messages.error(request, "پیشنهاد کارهای بعدی در حال حاضر آماده نشد. کمی بعد دوباره تلاش کنید.")
    else:
        if created:
            messages.success(request, f"{len(created)} پیشنهاد جدید برای کارهای بعدی پیدا شد.")
        else:
            messages.info(request, "در مدارک فعلی پیشنهاد تازه و قابل اتکایی برای کار بعدی پیدا نشد.")
    return redirect("portal:case-repository", case_code=case.case_code)


@login_required
@require_POST
def accept_case_action_suggestion_view(request, case_code: str, suggestion_id):
    case = _accessible_case(request.user, case_code)
    suggestion = get_object_or_404(CaseActionSuggestion, pk=suggestion_id, case=case)
    accept_action_suggestion(suggestion=suggestion, user=request.user)
    messages.success(request, "پیشنهاد به کارهای پرونده اضافه شد.")
    return redirect("portal:case-repository", case_code=case.case_code)


@login_required
@require_POST
def reject_case_action_suggestion_view(request, case_code: str, suggestion_id):
    case = _accessible_case(request.user, case_code)
    suggestion = get_object_or_404(CaseActionSuggestion, pk=suggestion_id, case=case)
    reject_action_suggestion(suggestion=suggestion, user=request.user)
    messages.info(request, "پیشنهاد کنار گذاشته شد.")
    return redirect("portal:case-repository", case_code=case.case_code)

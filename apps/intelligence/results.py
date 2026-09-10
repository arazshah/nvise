from django.db import transaction
from django.utils import timezone

from apps.cases.models import Case, CaseEvent

from .fact_ledger import latest_fact_ledger, ledger_quality_summary
from .models import CaseFieldIssue, ExtractedFact


RESOLVE_ISSUES_LABEL = "🧩 رفع موارد"
ADD_EVIDENCE_LABEL = "📎 افزودن مدرک بیشتر"
CONTINUE_CURRENT_LABEL = "⏭ ادامه با اطلاعات فعلی"
GENERATE_REPORT_LABEL = "📄 تولید گزارش"
VIEW_ANALYSIS_LABEL = "🧠 مشاهده نتیجه تحلیل"
HOME_MENU_LABEL = "🏠 منوی اصلی"
NEW_CASE_LABEL = "➕ پرونده جدید"
MY_CASES_LABEL = "📂 پرونده‌های من"


def analysis_result_summary(case: Case) -> dict:
    latest_run = case.extraction_runs.order_by("-created_at").first()
    facts = ExtractedFact.objects.filter(case=case)
    if latest_run is not None:
        facts = facts.filter(extraction_run=latest_run)

    usable_facts = facts.exclude(status=ExtractedFact.Status.REJECTED).exclude(
        status=ExtractedFact.Status.CONFLICTED
    ).count()
    issues = CaseFieldIssue.objects.filter(case=case, status=CaseFieldIssue.Status.OPEN)
    missing = issues.filter(issue_type=CaseFieldIssue.IssueType.MISSING).count()
    conflicts = issues.filter(issue_type=CaseFieldIssue.IssueType.CONFLICT).count()
    invalid = issues.filter(issue_type=CaseFieldIssue.IssueType.INVALID).count()
    open_issues = missing + conflicts + invalid
    quality = ledger_quality_summary(case)

    return {
        "usable_facts": usable_facts,
        "open_issues": open_issues,
        "missing": missing,
        "conflicts": conflicts,
        "invalid": invalid,
        "has_issues": open_issues > 0,
        "sourced_facts": quality["sourced"],
        "high_confidence_facts": quality["high_confidence"],
    }


def analysis_result_keyboard(case: Case) -> dict:
    summary = analysis_result_summary(case)
    rows = []
    if summary["has_issues"]:
        rows.append([{"text": RESOLVE_ISSUES_LABEL}, {"text": ADD_EVIDENCE_LABEL}])
        rows.append([{"text": CONTINUE_CURRENT_LABEL}])
    else:
        rows.append([{"text": GENERATE_REPORT_LABEL}, {"text": ADD_EVIDENCE_LABEL}])

    rows.append([{"text": NEW_CASE_LABEL}, {"text": MY_CASES_LABEL}])
    rows.append([{"text": HOME_MENU_LABEL}])
    return {"keyboard": rows, "resize_keyboard": True}


def _render_fact_preview(case: Case, limit: int = 5) -> list[str]:
    rows = latest_fact_ledger(case)
    if not rows:
        return []
    lines = ["", "📌 چند یافته مستند پرونده"]
    for row in rows[:limit]:
        value = str(row["value"])
        if len(value) > 120:
            value = value[:117] + "..."
        source = row["sources"][0]["label"] if row["sources"] else "بدون منبع مستقیم"
        confidence = row["confidence"]
        confidence_text = ""
        if confidence is not None:
            confidence_text = f" · اطمینان {round(confidence * 100)}٪"
        lines.append(f"• {row['label']}: {value}")
        lines.append(f"  ↳ {source}{confidence_text}")
    if len(rows) > limit:
        lines.append(f"… و {len(rows) - limit} یافته دیگر")
    return lines


def analysis_result_text(case: Case) -> str:
    summary = analysis_result_summary(case)
    lines = [
        "🧠 نتیجه تحلیل پرونده",
        "━━━━━━━━━━━━━━",
        f"📝 {case.title or case.case_code}",
        "",
        f"✅ اطلاعات قابل استفاده: {summary['usable_facts']}",
        f"🔗 یافته‌های متصل به مدرک: {summary['sourced_facts']}",
        f"🎯 یافته‌های با اطمینان بالا: {summary['high_confidence_facts']}",
        f"⚠️ موارد مبهم یا متناقض: {summary['conflicts'] + summary['invalid']}",
        f"❓ موارد واقعاً پیدا نشده: {summary['missing']}",
    ]
    lines.extend(_render_fact_preview(case))
    if summary["has_issues"]:
        lines.extend(
            [
                "",
                f"در مجموع {summary['open_issues']} مورد نیاز به تصمیم یا بررسی شما دارد.",
                "نویسه ابتدا مدارک و صوت‌های پرونده را بررسی کرده است؛ اگر هنوز موردی باز مانده، می‌توانید آن را رفع کنید، مدرک بیشتری اضافه کنید یا با اطلاعات فعلی ادامه دهید.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "✅ برای تحلیل فعلی مورد حل‌نشده‌ای باقی نمانده است.",
                "اگر آماده هستید می‌توانید گزارش را تولید کنید یا مدرک بیشتری به پرونده اضافه کنید.",
            ]
        )
    lines.extend(
        [
            "",
            "برای کار روی پرونده دیگری یا ساخت پرونده جدید، از دکمه‌های پایین استفاده کنید.",
        ]
    )
    return "\n".join(lines)


@transaction.atomic
def waive_open_issues(case: Case, actor=None) -> int:
    now = timezone.now()
    issues = list(
        CaseFieldIssue.objects.select_for_update().filter(
            case=case,
            status=CaseFieldIssue.Status.OPEN,
        )
    )
    if not issues:
        return 0

    for issue in issues:
        issue.status = CaseFieldIssue.Status.WAIVED
        issue.resolution_note = "کاربر خواست با اطلاعات فعلی ادامه داده شود."
        issue.resolved_at = now
    CaseFieldIssue.objects.bulk_update(issues, ["status", "resolution_note", "resolved_at"])

    locked_case = Case.objects.select_for_update().get(pk=case.pk)
    locked_case.analysis_status = Case.AnalysisStatus.COMPLETED
    if locked_case.status == Case.Status.NEEDS_INFORMATION:
        locked_case.status = Case.Status.OPEN
    locked_case.save(update_fields=["analysis_status", "status", "updated_at"])
    CaseEvent.objects.create(
        case=locked_case,
        event_type="case.analysis_issues_waived",
        actor=actor,
        payload={"count": len(issues)},
    )
    return len(issues)

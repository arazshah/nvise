from dataclasses import dataclass

from .models import Case


@dataclass(frozen=True)
class CaseStatusPresentation:
    label: str
    icon: str
    description: str


CASE_STATUS_PRESENTATIONS = {
    Case.Status.DRAFT: CaseStatusPresentation(
        "پیش‌نویس",
        "📝",
        "پرونده ایجاد شده اما هنوز برای دریافت کامل اطلاعات باز نشده است.",
    ),
    Case.Status.OPEN: CaseStatusPresentation(
        "در حال دریافت اطلاعات",
        "🟢",
        "می‌توانید متن، صوت، تصویر و مدارک بیشتری برای این پرونده ارسال کنید.",
    ),
    Case.Status.FINALIZING: CaseStatusPresentation(
        "در حال تحلیل و آماده‌سازی",
        "🔵",
        "نویسه در حال پردازش اطلاعات و بررسی کامل بودن پرونده است.",
    ),
    Case.Status.NEEDS_INFORMATION: CaseStatusPresentation(
        "نیازمند تکمیل اطلاعات",
        "🟠",
        "برای تکمیل پرونده باید به سؤال‌های تکمیلی نویسه پاسخ دهید.",
    ),
    Case.Status.READY_FOR_REVIEW: CaseStatusPresentation(
        "آماده بررسی و تأیید",
        "🟣",
        "گزارش آماده شده و منتظر بررسی و تأیید نهایی شماست.",
    ),
    Case.Status.APPROVED: CaseStatusPresentation(
        "تأیید شده",
        "✅",
        "گزارش این پرونده تأیید شده است.",
    ),
    Case.Status.ARCHIVED: CaseStatusPresentation(
        "بایگانی شده",
        "📦",
        "پرونده بایگانی شده و در چرخه فعال قرار ندارد.",
    ),
    Case.Status.CANCELLED: CaseStatusPresentation(
        "لغو شده",
        "⛔",
        "رسیدگی به این پرونده لغو شده است.",
    ),
}


def case_status_presentation(status: str) -> CaseStatusPresentation:
    return CASE_STATUS_PRESENTATIONS.get(
        status,
        CaseStatusPresentation("وضعیت نامشخص", "⚪", "وضعیت پرونده در حال بررسی است."),
    )


def case_status_label(status: str, *, with_icon: bool = True) -> str:
    item = case_status_presentation(status)
    return f"{item.icon} {item.label}" if with_icon else item.label


def case_status_description(status: str) -> str:
    return case_status_presentation(status).description

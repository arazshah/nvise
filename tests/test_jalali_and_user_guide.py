import re
from datetime import date
from pathlib import Path

from apps.system.jalali import format_jalali


def test_gregorian_date_is_formatted_as_jalali():
    assert format_jalali(date(2026, 10, 9)) == "1405/07/17"


def test_public_guide_avoids_internal_payment_implementation_details():
    guide = Path("templates/system/guide.html").read_text(encoding="utf-8")
    forbidden = ["sendInvoice", "pre_checkout_query", "SuccessfulPayment", "migration", "توکن پرداخت", "Admin"]
    for term in forbidden:
        assert term not in guide

    assert "➕ پرونده جدید" in guide
    assert "💳 اشتراک و مصرف" in guide
    assert "🌐 ورود به پنل نویسه" in guide
    assert "🏠 منوی اصلی" in guide


def test_public_guide_covers_complete_user_capability_reference():
    guide = Path("templates/system/guide.html").read_text(encoding="utf-8")
    required_topics = [
        "فهرست کامل حرفه‌ها و تخصص‌ها",
        "فرمت‌های پشتیبانی‌شده",
        "PDF",
        "DOCX",
        "فایل DOC قدیمی",
        "وضعیت پردازش",
        "تحلیل ناموفق",
        "بازسازی گزارش",
        "ادعاهای مهم",
        "دانلود Word",
        "پذیرش پیشنهاد",
        "رد پیشنهاد",
        "پرونده بدون اقدام",
        "یک‌بارمصرف",
        "سهمیه تبدیل صوت",
        "محدودیت‌های فایل",
        "موقعیت مکانی",
    ]
    missing = [topic for topic in required_topics if topic not in guide]
    assert not missing, f"Guide is missing capability topics: {missing}"


def test_public_guide_has_unique_numbered_sections():
    guide = Path("templates/system/guide.html").read_text(encoding="utf-8")
    headings = re.findall(r"<h2>([۱۲۳۴۵۶۷۸۹۰]+)\.", guide)
    assert len(headings) == len(set(headings))

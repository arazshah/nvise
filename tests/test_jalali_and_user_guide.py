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

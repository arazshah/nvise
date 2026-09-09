from django import template
from django.utils import timezone

from apps.system.jalali import format_jalali

register = template.Library()


@register.filter
def jalali_date(value):
    if value is None:
        return "—"
    if hasattr(value, "tzinfo") and timezone.is_aware(value):
        value = timezone.localtime(value)
    return format_jalali(value, include_time=False)


@register.filter
def jalali_datetime(value):
    if value is None:
        return "—"
    if hasattr(value, "tzinfo") and timezone.is_aware(value):
        value = timezone.localtime(value)
    return format_jalali(value, include_time=True)

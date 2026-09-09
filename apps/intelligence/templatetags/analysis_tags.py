from django import template

from apps.intelligence.results import analysis_result_summary

register = template.Library()


@register.simple_tag
def analysis_summary(case):
    return analysis_result_summary(case)

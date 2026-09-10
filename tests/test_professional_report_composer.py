import json

import pytest

from apps.accounts.models import User
from apps.cases.services import create_case
from apps.intelligence.playbooks import resolve_playbook
from apps.reports.composer import compose_professional_report, fallback_report
from apps.system.models import IntegrationSettings
from apps.tenants.models import Tenant, TenantMembership


def _case(*, profession, specialty=""):
    user = User.objects.create_user(username=f"report-{profession}", profession_key=profession, specialty_key=specialty)
    tenant = Tenant.objects.create(name="Personal", slug=f"report-{profession}")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده نمونه")
    return case


@pytest.mark.django_db
def test_fallback_uses_professional_playbook_sections():
    case = _case(profession=User.Profession.LAWYER, specialty="contracts")
    report = fallback_report(
        case=case,
        facts={"party_name": {"label": "طرف پرونده", "value": "شرکت نمونه", "confidence": 0.9, "evidence": []}},
        limitations=[],
    )
    playbook = resolve_playbook(case)
    assert [section["title"] for section in report["sections"]] == list(playbook.report_sections)
    assert report["composer"] == "fallback"


@pytest.mark.django_db
def test_composer_accepts_only_playbook_section_keys(monkeypatch):
    case = _case(profession=User.Profession.INSURANCE_LOSS_ADJUSTER, specialty="property_fire")
    settings = IntegrationSettings.get_solo()
    settings.avalai_enabled = True
    settings.avalai_api_key = "test-key"
    settings.save()
    playbook = resolve_playbook(case)

    class Response:
        headers = {}
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "model": "test-model",
                "choices": [{"message": {"content": json.dumps({
                    "title": "گزارش کارشناسی",
                    "summary": "خلاصه حرفه‌ای",
                    "sections": [
                        {"key": f"section_{i + 1}", "title": title, "content": f"متن بخش {i + 1}"}
                        for i, title in enumerate(playbook.report_sections)
                    ],
                }, ensure_ascii=False)}}],
            }

    monkeypatch.setattr("apps.reports.composer.httpx.post", lambda *args, **kwargs: Response())
    result = compose_professional_report(case=case, facts={}, limitations=[])
    assert result["composer"] == "avalai"
    assert result["model"] == "test-model"
    assert [section["title"] for section in result["sections"]] == list(playbook.report_sections)


@pytest.mark.django_db
def test_invalid_ai_structure_falls_back_safely(monkeypatch):
    case = _case(profession=User.Profession.TECHNICAL_EXPERT, specialty="industrial")
    settings = IntegrationSettings.get_solo()
    settings.avalai_enabled = True
    settings.avalai_api_key = "test-key"
    settings.save()

    class Response:
        headers = {}
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "model": "test-model",
                "choices": [{"message": {"content": json.dumps({
                    "title": "Bad",
                    "summary": "Bad",
                    "sections": [{"key": "invented", "title": "ساختگی", "content": "متن"}],
                }, ensure_ascii=False)}}],
            }

    monkeypatch.setattr("apps.reports.composer.httpx.post", lambda *args, **kwargs: Response())
    result = compose_professional_report(case=case, facts={}, limitations=[])
    assert result["composer"] == "fallback"
    assert [section["title"] for section in result["sections"]] == list(resolve_playbook(case).report_sections)

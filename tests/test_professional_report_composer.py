import json
from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.cases.services import create_case
from apps.intelligence.playbooks import resolve_playbook
from apps.reports.composer import compose_professional_report, fallback_report
from apps.tenants.models import Tenant, TenantMembership


def _case(*, profession, specialty=""):
    user = User.objects.create_user(username=f"report-{profession}", profession_key=profession, specialty_key=specialty)
    tenant = Tenant.objects.create(name="Personal", slug=f"report-{profession}")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="پرونده نمونه")
    return case


def _mock_avalai(monkeypatch):
    monkeypatch.setattr(
        "apps.reports.composer.get_avalai_config",
        lambda: SimpleNamespace(
            enabled=True,
            api_key="test-key",
            base_url="https://api.example.test/v1",
            text_model="test-model",
            timeout_seconds=30,
        ),
    )


def _expected_sections(playbook):
    rows = []
    for index, title in enumerate(playbook.report_sections):
        key = "limitations" if "محدودیت" in title else f"section_{index + 1}"
        rows.append({"key": key, "title": title})
    return rows


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
    _mock_avalai(monkeypatch)
    playbook = resolve_playbook(case)
    expected = _expected_sections(playbook)

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
                        {"key": item["key"], "title": item["title"], "content": f"متن بخش {index + 1}"}
                        for index, item in enumerate(expected)
                    ],
                }, ensure_ascii=False)}}],
            }

    monkeypatch.setattr("apps.reports.composer.httpx.post", lambda *args, **kwargs: Response())
    result = compose_professional_report(case=case, facts={}, limitations=[])
    assert result["composer"] == "avalai"
    assert result["model"] == "test-model"
    assert [section["key"] for section in result["sections"]] == [item["key"] for item in expected]
    assert [section["title"] for section in result["sections"]] == list(playbook.report_sections)


@pytest.mark.django_db
def test_invalid_ai_structure_falls_back_safely(monkeypatch):
    case = _case(profession=User.Profession.TECHNICAL_EXPERT, specialty="industrial")
    _mock_avalai(monkeypatch)

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

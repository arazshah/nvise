import pytest

from apps.accounts.models import User
from apps.cases.services import create_case
from apps.intelligence.playbooks import PLAYBOOKS, resolve_playbook, serialize_playbook
from apps.tenants.models import Tenant, TenantMembership


def _case(username: str, profession: str = ""):
    user = User.objects.create_user(username=username, profession_key=profession)
    tenant = Tenant.objects.create(name="Personal", slug=username)
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    return user, create_case(user=user, tenant=tenant, title="Playbook case")


@pytest.mark.django_db
def test_insurance_profession_resolves_insurance_playbook():
    _, case = _case("playbook-insurance", User.Profession.INSURANCE_LOSS_ADJUSTER)
    playbook = resolve_playbook(case)
    assert playbook.key == User.Profession.INSURANCE_LOSS_ADJUSTER
    assert "policy_coverage" in playbook.analysis_dimensions
    assert "damage_quantum" in playbook.analysis_dimensions


@pytest.mark.django_db
def test_lawyer_profession_changes_analysis_lens():
    user, case = _case("playbook-lawyer", User.Profession.LAWYER)
    user.specialty_key = "contract_disputes"
    user.save(update_fields=["specialty_key"])
    payload = serialize_playbook(case)
    assert payload["key"] == User.Profession.LAWYER
    assert payload["specialty"] == "contract_disputes"
    assert "claims_and_defenses" in payload["analysis_dimensions"]
    assert "policy_coverage" not in payload["analysis_dimensions"]


@pytest.mark.django_db
def test_technical_profession_has_root_cause_lens():
    _, case = _case("playbook-technical", User.Profession.TECHNICAL_EXPERT)
    payload = serialize_playbook(case)
    assert "root_cause" in payload["analysis_dimensions"]
    assert "failure_mechanism" in payload["analysis_dimensions"]


@pytest.mark.django_db
def test_unset_profile_falls_back_to_insurance_for_insurance_case():
    _, case = _case("playbook-fallback")
    case.vertical_key = "insurance"
    case.sub_vertical_key = "fire_loss"
    case.save(update_fields=["vertical_key", "sub_vertical_key"])
    assert resolve_playbook(case) == PLAYBOOKS[User.Profession.INSURANCE_LOSS_ADJUSTER]

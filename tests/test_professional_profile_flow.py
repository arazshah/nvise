import pytest

from apps.accounts.models import User
from apps.cases.services import create_case
from apps.intelligence.catalog import ensure_schema_for_case
from apps.intelligence.playbooks import resolve_playbook
from apps.intelligence.professional_catalog import case_types_for, find_case_type, specialties_for
from apps.tenants.models import Tenant, TenantMembership


@pytest.mark.django_db
def test_lawyer_contract_case_resolves_legal_schema_and_playbook():
    user = User.objects.create_user(
        username="lawyer-profile",
        profession_key=User.Profession.LAWYER,
        specialty_key="contracts",
    )
    tenant = Tenant.objects.create(name="Legal", slug="legal-profile")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="اختلاف قرارداد")
    option = find_case_type(user.profession_key, user.specialty_key, "contract_dispute")
    assert option is not None
    case.case_type_key = option.key
    case.vertical_key = option.vertical_key
    case.sub_vertical_key = option.sub_vertical_key
    case.save(update_fields=["case_type_key", "vertical_key", "sub_vertical_key"])

    schema = ensure_schema_for_case(case)
    playbook = resolve_playbook(case)

    assert schema.sub_vertical.vertical.key == "legal"
    assert schema.sub_vertical.key == "contract_dispute"
    assert schema.fields.filter(key="parties").exists()
    assert playbook.key == User.Profession.LAWYER
    assert "legal_issues" in playbook.analysis_dimensions


@pytest.mark.django_db
def test_technical_case_resolves_technical_schema():
    user = User.objects.create_user(
        username="technical-profile",
        profession_key=User.Profession.TECHNICAL_EXPERT,
        specialty_key="industrial",
    )
    tenant = Tenant.objects.create(name="Technical", slug="technical-profile")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="خرابی دستگاه")
    option = find_case_type(user.profession_key, user.specialty_key, "failure_analysis")
    assert option is not None
    case.case_type_key = option.key
    case.vertical_key = option.vertical_key
    case.sub_vertical_key = option.sub_vertical_key
    case.save(update_fields=["case_type_key", "vertical_key", "sub_vertical_key"])

    schema = ensure_schema_for_case(case)

    assert schema.sub_vertical.vertical.key == "technical"
    assert schema.fields.filter(key="root_cause").exists()


def test_catalog_limits_case_types_to_selected_profession_and_specialty():
    assert specialties_for(User.Profession.LAWYER)
    assert case_types_for(User.Profession.LAWYER, "contracts")
    assert find_case_type(User.Profession.LAWYER, "contracts", "fire_loss") is None
    assert find_case_type(User.Profession.INSURANCE_LOSS_ADJUSTER, "property_fire", "fire_loss") is not None

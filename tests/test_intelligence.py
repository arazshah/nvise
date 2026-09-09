import pytest

from apps.accounts.models import User
from apps.cases.services import create_case
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.models import CaseFieldIssue, ExtractionRun
from apps.intelligence.services import apply_extraction_response, supplemental_questions
from apps.tenants.models import Tenant, TenantMembership


@pytest.mark.django_db
def test_fire_loss_schema_and_missing_questions():
    user = User.objects.create_user(username="expert")
    tenant = Tenant.objects.create(name="Personal", slug="personal-test")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="Fire loss")
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(case=case, schema=schema, provider="test")

    apply_extraction_response(
        run=run,
        response={
            "facts": [
                {"field": "insured_name", "value": "آراز شاهکرمی", "confidence": 0.99}
            ],
            "conflicts": [],
        },
    )

    assert schema.fields.filter(required=True).exists()
    assert CaseFieldIssue.objects.filter(
        case=case,
        issue_type=CaseFieldIssue.IssueType.MISSING,
    ).exists()
    questions = supplemental_questions(case)
    assert questions
    assert any("نشانی محل حادثه" in question for question in questions)

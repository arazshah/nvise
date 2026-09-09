from io import BytesIO
from zipfile import ZipFile

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.cases.models import Case
from apps.cases.services import create_case, finish_input, transition_case
from apps.documents.models import GeneratedDocument
from apps.documents.renderer import render_revision_docx
from apps.intelligence.catalog import ensure_fire_loss_schema
from apps.intelligence.models import ExtractionRun, ExtractedFact
from apps.portal.models import ReviewAccessToken
from apps.portal.services import create_review_access_token, consume_review_access_token
from apps.reports.services import generate_report_revision
from apps.tenants.models import Tenant, TenantMembership


def _fixture():
    user = User.objects.create_user(username="reviewer")
    tenant = Tenant.objects.create(name="Review Tenant", slug="review-tenant")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)
    case = create_case(user=user, tenant=tenant, title="Fire Review")
    return user, case


@pytest.mark.django_db
def test_review_access_token_is_hashed_short_lived_and_one_time():
    user, case = _fixture()
    raw = create_review_access_token(user=user, case=case, ttl_minutes=15)
    assert raw
    row = ReviewAccessToken.objects.get(case=case)
    assert raw not in row.token_hash
    assert row.expires_at > timezone.now()

    consumed = consume_review_access_token(raw)
    assert consumed.user == user
    assert consumed.consumed_at is not None
    with pytest.raises(ValueError):
        consume_review_access_token(raw)


@pytest.mark.django_db
def test_report_revision_renders_valid_docx():
    user, case = _fixture()
    schema = ensure_fire_loss_schema()
    run = ExtractionRun.objects.create(
        case=case,
        schema=schema,
        provider="test",
        status=ExtractionRun.Status.COMPLETED,
        completed_at=timezone.now(),
    )
    field = schema.fields.get(key="insured_name")
    ExtractedFact.objects.create(
        case=case,
        field=field,
        extraction_run=run,
        value="آراز شاهکرمی",
        normalized_value="آراز شاهکرمی",
        confidence=0.99,
    )
    case = finish_input(case=case, actor=user)
    case = transition_case(case=case, target_status=Case.Status.READY_FOR_REVIEW, actor=user)
    revision = generate_report_revision(case=case, created_by=user)

    payload = render_revision_docx(revision)
    assert payload.startswith(b"PK")
    with ZipFile(BytesIO(payload)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "آراز شاهکرمی" in xml
    assert case.case_code in xml
    assert not GeneratedDocument.objects.exists()

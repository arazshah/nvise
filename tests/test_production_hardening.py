from unittest.mock import Mock, patch

import pytest
from django.test import Client, override_settings

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.cases.services import create_case, finish_input
from apps.tenants.models import Tenant, TenantMembership


@pytest.mark.django_db
def test_liveness_includes_request_id_header():
    response = Client().get("/health/live/", HTTP_X_REQUEST_ID="pilot-request-1")
    assert response.status_code == 200
    assert response["X-Request-ID"] == "pilot-request-1"
    assert response.json()["check"] == "liveness"


@pytest.mark.django_db
def test_readiness_checks_database_and_redis():
    redis_client = Mock()
    redis_client.ping.return_value = True
    with patch("apps.system.views.redis.Redis.from_url", return_value=redis_client):
        response = Client().get("/health/ready/")
    assert response.status_code == 200
    assert response.json()["dependencies"] == {"database": True, "redis": True}


@pytest.mark.django_db
def test_case_lifecycle_creates_audit_events():
    user = User.objects.create_user(username="pilot-auditor")
    tenant = Tenant.objects.create(name="Pilot", slug="pilot-audit")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)

    case = create_case(user=user, tenant=tenant, title="Pilot fire case")
    finish_input(case=case, actor=user)

    assert AuditEvent.objects.filter(case=case, event_type="case.created").exists()
    analysis = AuditEvent.objects.filter(case=case, event_type="case.analysis_requested").latest("created_at")
    assert analysis.metadata["from"] == "not_started"
    assert analysis.metadata["to"] == "queued"


@pytest.mark.django_db
@override_settings(BALE_WEBHOOK_SECRET="test-secret")
def test_bale_webhook_rate_limit_returns_429():
    with patch("apps.messaging.views.allow_fixed_window", return_value=False):
        response = Client().post(
            "/webhooks/bale/test-secret/",
            data='{"update_id": 1}',
            content_type="application/json",
        )
    assert response.status_code == 429
    assert response["Retry-After"] == "60"

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.portal.models import PortalAccessToken
from apps.portal.services import create_portal_access_token
from apps.tenants.models import Tenant, TenantMembership


@pytest.mark.django_db
def test_portal_magic_link_is_not_consumed_on_preview_and_is_one_time(client):
    user = User.objects.create_user(username="bale_magic_user")
    tenant = Tenant.objects.create(name="Personal", slug="portal-magic-test")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)

    raw_token = create_portal_access_token(
        user=user,
        provider="bale",
        external_chat_id="12345",
        ttl_minutes=2,
    )
    url = reverse("portal:portal-access", kwargs={"token": raw_token})

    preview = client.get(url)
    assert preview.status_code == 200
    token_row = PortalAccessToken.objects.get(user=user)
    assert token_row.consumed_at is None

    login_response = client.post(url)
    assert login_response.status_code == 302
    assert login_response.url == reverse("portal:case-list")
    token_row.refresh_from_db()
    assert token_row.consumed_at is not None
    assert client.session.get("_auth_user_id") == str(user.pk)

    second_use = client.post(url)
    assert second_use.status_code == 400


@pytest.mark.django_db
def test_new_portal_magic_link_revokes_previous_unused_link():
    user = User.objects.create_user(username="bale_magic_rotate")
    tenant = Tenant.objects.create(name="Personal", slug="portal-magic-rotate-test")
    TenantMembership.objects.create(tenant=tenant, user=user, role=TenantMembership.Role.OWNER)

    first = create_portal_access_token(user=user, external_chat_id="100", ttl_minutes=2)
    second = create_portal_access_token(user=user, external_chat_id="100", ttl_minutes=2)

    first_row = PortalAccessToken.objects.exclude(token_hash=PortalAccessToken.objects.order_by("-created_at").first().token_hash).first()
    assert first != second
    assert first_row is not None
    assert first_row.revoked_at is not None

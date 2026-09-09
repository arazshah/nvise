import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.cases.models import Case
from apps.tenants.models import TenantMembership

from .models import PortalAccessToken, ReviewAccessToken


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def user_can_review_case(*, user, case: Case) -> bool:
    return TenantMembership.objects.filter(
        tenant=case.tenant,
        user=user,
        is_active=True,
        tenant__is_active=True,
    ).exists()


def user_has_portal_access(user) -> bool:
    return user.is_active and TenantMembership.objects.filter(
        user=user,
        is_active=True,
        tenant__is_active=True,
    ).exists()


@transaction.atomic
def create_portal_access_token(
    *,
    user,
    provider: str = "bale",
    external_chat_id: str = "",
    ttl_minutes: int = 2,
) -> str:
    if not user_has_portal_access(user):
        raise PermissionError("User has no active tenant membership")

    now = timezone.now()
    PortalAccessToken.objects.filter(
        user=user,
        consumed_at__isnull=True,
        revoked_at__isnull=True,
        expires_at__gt=now,
    ).update(revoked_at=now)

    raw_token = secrets.token_urlsafe(32)
    PortalAccessToken.objects.create(
        user=user,
        token_hash=_hash_token(raw_token),
        provider=provider[:32],
        external_chat_id=external_chat_id[:128],
        expires_at=now + timedelta(minutes=ttl_minutes),
    )
    return raw_token


def get_portal_access_token(raw_token: str) -> PortalAccessToken | None:
    return PortalAccessToken.objects.select_related("user").filter(
        token_hash=_hash_token(raw_token)
    ).first()


@transaction.atomic
def consume_portal_access_token(raw_token: str) -> PortalAccessToken:
    token = (
        PortalAccessToken.objects.select_for_update()
        .select_related("user")
        .get(token_hash=_hash_token(raw_token))
    )
    now = timezone.now()
    if token.consumed_at is not None:
        raise ValueError("Portal access token has already been used")
    if token.revoked_at is not None:
        raise ValueError("Portal access token has been revoked")
    if token.expires_at <= now:
        raise ValueError("Portal access token has expired")
    if not user_has_portal_access(token.user):
        raise PermissionError("Portal access is no longer valid")

    token.consumed_at = now
    token.save(update_fields=["consumed_at"])
    return token


@transaction.atomic
def create_review_access_token(*, user, case: Case, ttl_minutes: int = 15) -> str:
    if not user_can_review_case(user=user, case=case):
        raise PermissionError("User is not an active member of the case tenant")
    raw_token = secrets.token_urlsafe(32)
    ReviewAccessToken.objects.create(
        user=user,
        case=case,
        token_hash=_hash_token(raw_token),
        expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
    )
    return raw_token


@transaction.atomic
def consume_review_access_token(raw_token: str) -> ReviewAccessToken:
    token = (
        ReviewAccessToken.objects.select_for_update()
        .select_related("user", "case__tenant")
        .get(token_hash=_hash_token(raw_token))
    )
    now = timezone.now()
    if token.consumed_at is not None:
        raise ValueError("Review access token has already been used")
    if token.expires_at <= now:
        raise ValueError("Review access token has expired")
    if not token.user.is_active or not user_can_review_case(user=token.user, case=token.case):
        raise PermissionError("Review access is no longer valid")
    token.consumed_at = now
    token.save(update_fields=["consumed_at"])
    return token

import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.cases.models import Case
from apps.tenants.models import TenantMembership

from .models import ReviewAccessToken


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def user_can_review_case(*, user, case: Case) -> bool:
    return TenantMembership.objects.filter(
        tenant=case.tenant,
        user=user,
        is_active=True,
        tenant__is_active=True,
    ).exists()


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

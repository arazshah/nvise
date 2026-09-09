from django.db import transaction

from .models import Tenant, TenantMembership


class MemberLimitExceededError(PermissionError):
    pass


@transaction.atomic
def add_tenant_member(*, tenant: Tenant, user, role: str = TenantMembership.Role.EXPERT):
    existing = TenantMembership.objects.select_for_update().filter(tenant=tenant, user=user).first()
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            existing.role = role
            existing.save(update_fields=["is_active", "role"])
        return existing

    from apps.subscriptions.services import get_or_create_subscription

    subscription = get_or_create_subscription(tenant)
    active_count = TenantMembership.objects.filter(tenant=tenant, is_active=True).count()
    if active_count >= subscription.plan.max_members:
        raise MemberLimitExceededError(
            f"Tenant member limit reached ({active_count}/{subscription.plan.max_members})"
        )
    return TenantMembership.objects.create(tenant=tenant, user=user, role=role)

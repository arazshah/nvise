import uuid

from django.conf import settings
from django.db import models

from apps.cases.models import Case


class ReviewAccessToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_access_tokens",
    )
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="review_access_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Profession(models.TextChoices):
        INSURANCE_LOSS_ADJUSTER = "insurance_loss_adjuster", "کارشناس ارزیاب خسارت بیمه"
        LAWYER = "lawyer", "وکیل / کارشناس حقوقی"
        TECHNICAL_EXPERT = "technical_expert", "کارشناس / مشاور فنی"
        OTHER = "other", "سایر"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField(max_length=150, blank=True)
    profession_key = models.CharField(max_length=64, choices=Profession.choices, blank=True, db_index=True)
    specialty_key = models.CharField(max_length=96, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.display_name or self.username


class BaleIdentity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bale_identity",
    )
    external_user_id = models.CharField(max_length=128, unique=True)
    external_chat_id = models.CharField(max_length=128, db_index=True)
    username = models.CharField(max_length=150, blank=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"bale:{self.external_user_id}"

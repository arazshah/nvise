import uuid

from django.conf import settings
from django.db import models

from apps.cases.models import Case


class InboundUpdate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=32)
    bot_id = models.CharField(max_length=128)
    external_update_id = models.CharField(max_length=128)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "bot_id", "external_update_id"],
                name="uniq_provider_bot_update",
            )
        ]


class CaseMessage(models.Model):
    class MessageType(models.TextChoices):
        TEXT = "text", "Text"
        VOICE = "voice", "Voice"
        AUDIO = "audio", "Audio"
        IMAGE = "image", "Image"
        DOCUMENT = "document", "Document"
        LOCATION = "location", "Location"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="messages")
    provider = models.CharField(max_length=32)
    external_chat_id = models.CharField(max_length=128)
    external_message_id = models.CharField(max_length=128)
    message_type = models.CharField(max_length=16, choices=MessageType.choices)
    text = models.TextField(blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sent_at", "received_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_chat_id", "external_message_id"],
                name="uniq_provider_chat_message",
            )
        ]


class ConversationState(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversation_states")
    provider = models.CharField(max_length=32)
    external_chat_id = models.CharField(max_length=128)
    active_case = models.ForeignKey(Case, null=True, blank=True, on_delete=models.SET_NULL, related_name="active_conversations")
    state = models.CharField(max_length=64, default="idle")
    pending_action = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "provider", "external_chat_id"],
                name="uniq_user_provider_chat_state",
            )
        ]

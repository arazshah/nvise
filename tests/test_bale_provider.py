from apps.messaging.providers.bale import BaleProvider
from apps.messaging.providers.bale.provider import BILLING_LABEL, PORTAL_LOGIN_LABEL


def test_bale_text_update_is_normalized():
    provider = BaleProvider()
    payload = {
        "update_id": 1001,
        "message": {
            "message_id": 77,
            "date": 1788920000,
            "from": {"id": 123, "first_name": "Araz"},
            "chat": {"id": 123, "type": "private"},
            "text": "پرونده جدید",
        },
    }

    update = provider.parse_update(payload)

    assert update.provider == "bale"
    assert update.update_id == "1001"
    assert update.message is not None
    assert update.message.external_user_id == "123"
    assert update.message.external_chat_id == "123"
    assert update.message.external_message_id == "77"
    assert update.message.message_type == "text"
    assert update.message.text == "پرونده جدید"


def test_bale_voice_update_is_normalized():
    provider = BaleProvider()
    payload = {
        "update_id": 1002,
        "message": {
            "message_id": 78,
            "date": 1788920001,
            "from": {"id": 123},
            "chat": {"id": 123},
            "voice": {
                "file_id": "voice-file-id",
                "file_size": 2048,
                "mime_type": "audio/ogg",
            },
        },
    }

    update = provider.parse_update(payload)

    assert update.message is not None
    assert update.message.message_type == "voice"
    assert update.message.file is not None
    assert update.message.file.file_id == "voice-file-id"
    assert update.message.file.file_size == 2048


def test_permanent_bale_menu_contains_billing_and_portal_entries():
    keyboard = BaleProvider._with_portal_button(
        {
            "keyboard": [[{"text": "➕ پرونده جدید"}]],
            "resize_keyboard": True,
        }
    )
    labels = [button["text"] for row in keyboard["keyboard"] for button in row]

    assert BILLING_LABEL in labels
    assert PORTAL_LOGIN_LABEL in labels


def test_one_time_keyboard_is_not_polluted_with_global_entries():
    keyboard = {
        "keyboard": [[{"text": "گزینه موقت"}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }

    assert BaleProvider._with_portal_button(keyboard) == keyboard


def test_bale_image_sent_as_document_is_normalized_as_image():
    provider = BaleProvider()
    payload = {
        "update_id": 1003,
        "message": {
            "message_id": 79,
            "date": 1788920002,
            "from": {"id": 123},
            "chat": {"id": 123},
            "document": {
                "file_id": "image-document-file-id",
                "file_name": "damage.jpg",
                "mime_type": "image/jpeg",
                "file_size": 4096,
            },
        },
    }

    update = provider.parse_update(payload)

    assert update.message is not None
    assert update.message.message_type == "image"
    assert update.message.file is not None
    assert update.message.file.file_name == "damage.jpg"

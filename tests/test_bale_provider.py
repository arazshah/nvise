from apps.messaging.providers.bale import BaleProvider


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

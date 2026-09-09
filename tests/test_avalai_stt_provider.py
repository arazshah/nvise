from apps.transcription.providers.avalai import (
    AvalAISTTProvider,
    _normalized_audio_filename,
    _response_format_for_model,
)


def test_normalizes_bale_voice_bin_filename_from_mime():
    assert _normalized_audio_filename("recording.bin", "audio/ogg") == "recording.ogg"
    assert _normalized_audio_filename("", "audio/webm") == "recording.webm"


def test_preserves_real_audio_extension():
    assert _normalized_audio_filename("voice.mp3", "audio/mpeg") == "voice.mp3"


def test_response_format_matches_model_capabilities():
    assert _response_format_for_model("gpt-4o-mini-transcribe") == "json"
    assert _response_format_for_model("gpt-4o-transcribe") == "json"
    assert _response_format_for_model("whisper-1") == "verbose_json"
    assert _response_format_for_model("gpt-4o-transcribe-diarize") == "diarized_json"


class FakeResponse:
    is_error = False
    headers = {"avalai-request-id": "req-123"}

    def json(self):
        return {"text": "سلام", "language": "fa"}


class FakeClient:
    last_kwargs = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        FakeClient.last_kwargs = kwargs
        return FakeResponse()


def test_avalai_provider_sends_supported_multipart_for_bale_voice(monkeypatch):
    monkeypatch.setattr("apps.transcription.providers.avalai.httpx.Client", FakeClient)
    provider = AvalAISTTProvider(
        base_url="https://api.avalai.ir/v1",
        api_key="secret",
        model="gpt-4o-mini-transcribe",
        language="fa",
    )

    result = provider.transcribe(
        content=b"audio-data",
        filename="recording.bin",
        mime_type="audio/ogg",
        language_hint="fa",
    )

    assert result.text == "سلام"
    assert FakeClient.last_kwargs["files"]["file"][0] == "recording.ogg"
    assert FakeClient.last_kwargs["files"]["file"][2] == "audio/ogg"
    assert FakeClient.last_kwargs["data"]["model"] == "gpt-4o-mini-transcribe"
    assert FakeClient.last_kwargs["data"]["response_format"] == "json"

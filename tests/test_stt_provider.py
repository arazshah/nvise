from apps.transcription.providers.http import HTTPSTTProvider


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "text": "سلام دنیا",
            "language": "fa",
            "model": "test-stt",
            "confidence": 0.91,
            "segments": [
                {"start": 0.25, "end": 1.5, "text": "سلام", "confidence": 0.95},
                {"start_ms": 1500, "end_ms": 2300, "text": "دنیا", "confidence": 0.88},
            ],
        }


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        return FakeResponse()


def test_http_stt_provider_normalizes_segments(monkeypatch):
    monkeypatch.setattr("apps.transcription.providers.http.httpx.Client", FakeClient)
    provider = HTTPSTTProvider(endpoint="https://stt.example.test/transcribe", api_key="secret")

    result = provider.transcribe(
        content=b"audio",
        filename="voice.ogg",
        mime_type="audio/ogg",
        language_hint="fa",
    )

    assert result.text == "سلام دنیا"
    assert result.language == "fa"
    assert result.model_name == "test-stt"
    assert result.segments[0].start_ms == 250
    assert result.segments[0].end_ms == 1500
    assert result.segments[1].start_ms == 1500
    assert result.segments[1].end_ms == 2300

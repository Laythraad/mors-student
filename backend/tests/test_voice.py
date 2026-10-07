"""نظام الصوت (§15/§70/§71): إعدادات قابلة للتبديل، نطق مُعبَّر، تعرّف محلي."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings as app_settings
from app.services import voice as voice_service


def test_voice_requires_auth(client: TestClient) -> None:
    assert client.get("/api/voice/config").status_code == 401
    assert client.post("/api/voice/speak", json={"text": "أهلاً"}).status_code == 401
    assert client.post("/api/voice/stt").status_code == 401


def test_voice_config_shape(client: TestClient, demo_headers: dict[str, str]) -> None:
    data = client.get("/api/voice/config", headers=demo_headers)
    assert data.status_code == 200, data.text
    payload = data.json()
    for key in (
        "tts_provider",
        "stt_provider",
        "tts_ready",
        "stt_ready",
        "default_voice",
        "styles",
        "realtime",
        "user",
    ):
        assert key in payload, key
    assert payload["tts_ready"] is True
    assert payload["realtime"] is False  # §70 real-time mode comes later
    assert "neutral" in payload["styles"] and "celebrating" in payload["styles"]
    assert payload["user"]["voice_enabled"] in (True, False)
    assert payload["user"]["tts_voice"]


def test_speak_maps_expression_to_tone(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    neutral = client.post(
        "/api/voice/speak", headers=demo_headers, json={"text": "أهلاً", "style": "neutral"}
    )
    assert neutral.status_code == 200, neutral.text
    base = neutral.json()
    assert base["provider"] == "browser"
    assert base["lang"] == "ar-IQ"
    assert base["rate"] == 1.0 and base["pitch"] == 1.0

    excited = client.post(
        "/api/voice/speak", headers=demo_headers, json={"text": "رائع!", "style": "excited"}
    )
    assert excited.status_code == 200, excited.text
    assert excited.json()["rate"] > base["rate"]
    assert excited.json()["pitch"] > base["pitch"]

    concerned = client.post(
        "/api/voice/speak", headers=demo_headers, json={"text": "خلنا نراجع", "style": "concerned"}
    )
    assert concerned.status_code == 200, concerned.text
    assert concerned.json()["rate"] < base["rate"]


def test_speak_validates_input(client: TestClient, demo_headers: dict[str, str]) -> None:
    empty = client.post("/api/voice/speak", headers=demo_headers, json={"text": ""})
    assert empty.status_code == 422

    blank = client.post("/api/voice/speak", headers=demo_headers, json={"text": "   "})
    assert blank.status_code == 422, blank.text

    too_long = client.post(
        "/api/voice/speak", headers=demo_headers, json={"text": "كلمة " * 300}
    )
    assert too_long.status_code == 422, too_long.text

    bad_style = client.post(
        "/api/voice/speak", headers=demo_headers, json={"text": "أهلاً", "style": "zombie"}
    )
    assert bad_style.status_code == 422, bad_style.text


def test_speak_reports_unavailable_provider(
    client: TestClient, demo_headers: dict[str, str], monkeypatch
) -> None:
    monkeypatch.setattr(app_settings, "ai_tts_provider", "openai")
    data = client.post("/api/voice/speak", headers=demo_headers, json={"text": "أهلاً"})
    assert data.status_code == 501, data.text
    assert data.json()["error"]["code"] == "unsupported"


def test_stt_browser_keeps_audio_local(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    data = client.post(
        "/api/voice/stt",
        headers=demo_headers,
        files={"audio": ("voice.wav", b"RIFF0000WAVEfake", "audio/wav")},
    )
    assert data.status_code == 200, data.text
    payload = data.json()
    assert payload["provider"] == "browser"
    assert payload["available"] is False
    assert payload["text"] == ""


def test_stt_mock_transcribes(
    client: TestClient, demo_headers: dict[str, str], monkeypatch
) -> None:
    monkeypatch.setattr(app_settings, "ai_stt_provider", "mock")
    data = client.post(
        "/api/voice/stt",
        headers=demo_headers,
        files={"audio": ("q.ogg", b"OggS-fake", "audio/ogg")},
    )
    assert data.status_code == 200, data.text
    payload = data.json()
    assert payload["available"] is True
    assert payload["text"] == voice_service.MOCK_TRANSCRIPT


def test_settings_persist_voice_prefs(
    client: TestClient, demo_headers: dict[str, str]
) -> None:
    patched = client.patch(
        "/api/auth/settings",
        headers=demo_headers,
        json={"voice_enabled": False, "tts_voice": "ar", "stt_provider": "mock"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()["settings"]
    assert body["voice_enabled"] is False
    assert body["tts_voice"] == "ar"
    assert body["stt_provider"] == "mock"

    config = client.get("/api/voice/config", headers=demo_headers).json()
    assert config["user"]["voice_enabled"] is False
    assert config["user"]["tts_voice"] == "ar"

    # restore defaults for the rest of the suite
    client.patch(
        "/api/auth/settings",
        headers=demo_headers,
        json={"voice_enabled": True, "tts_voice": "system", "stt_provider": "browser"},
    )

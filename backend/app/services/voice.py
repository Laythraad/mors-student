"""Voice I/O for Mors (§15 / §70): pluggable TTS + STT, text-first.

Pipeline (§15): Student Voice → STT → Mors → Response → TTS → Mors Voice.
Audio is always optional (§70): every payload carries enough data for the
browser to play it through Web Speech, or to stay silent without breaking the
text experience. Providers are read from config (§71) and can be swapped
without touching feature code — a new provider joins one of the tuples below.
"""

from __future__ import annotations

from typing import Any

from ..config import settings
from ..core.errors import UnsupportedFeatureError, ValidationError
from ..db import StudentSettings, User

# §17 — expression → voice tone (browser speech units: rate/pitch/volume)
STYLES: dict[str, dict[str, float]] = {
    "neutral": {"rate": 1.0, "pitch": 1.0, "volume": 1.0},
    "happy": {"rate": 1.05, "pitch": 1.1, "volume": 1.0},
    "proud": {"rate": 0.95, "pitch": 1.05, "volume": 1.0},
    "excited": {"rate": 1.15, "pitch": 1.2, "volume": 1.0},
    "celebrating": {"rate": 1.1, "pitch": 1.25, "volume": 1.0},
    "thinking": {"rate": 0.9, "pitch": 0.95, "volume": 0.95},
    "focused": {"rate": 1.0, "pitch": 0.95, "volume": 1.0},
    "concerned": {"rate": 0.85, "pitch": 0.9, "volume": 0.95},
    "sad": {"rate": 0.8, "pitch": 0.85, "volume": 0.9},
    "encouraging": {"rate": 0.95, "pitch": 1.05, "volume": 1.0},
    "surprised": {"rate": 1.05, "pitch": 1.3, "volume": 1.0},
    "welcoming": {"rate": 1.0, "pitch": 1.1, "volume": 1.0},
}

# providers implemented today — everything else waits for its key/config
TTS_PROVIDERS = ("browser", "mock")
STT_PROVIDERS = ("browser", "mock")

MOCK_TRANSCRIPT = "ما هو الفرق المشترك؟"
MAX_STT_BYTES = 8 * 1024 * 1024


def voice_config(db: Any, user: User) -> dict[str, Any]:
    """§70/§71 — what this deployment can do + the student's own voice prefs."""
    row = db.query(StudentSettings).filter(StudentSettings.user_id == user.id).one_or_none()
    return {
        "tts_provider": settings.ai_tts_provider,
        "stt_provider": settings.ai_stt_provider,
        "tts_ready": settings.ai_tts_provider in TTS_PROVIDERS,
        "stt_ready": settings.ai_stt_provider in STT_PROVIDERS,
        "default_voice": settings.ai_tts_voice,
        "max_chars": settings.ai_voice_max_chars,
        "styles": list(STYLES),
        "realtime": False,  # §70 real-time mode — later
        "user": {
            "voice_enabled": bool(row.voice_enabled) if row else True,
            "tts_voice": (row.tts_voice if row else "system") or "system",
            "stt_provider": (row.stt_provider if row else "browser") or "browser",
        },
    }


def _student_voice(db: Any, user: User | None) -> str:
    if db is None or user is None:
        return ""
    row = db.query(StudentSettings).filter(StudentSettings.user_id == user.id).one_or_none()
    return ((row.tts_voice if row else "") or "").strip()


def speak(
    db: Any,
    user: User,
    text: str,
    *,
    style: str = "neutral",
    voice: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """§15 — turn a Mors reply into a playable, tone-tagged payload.

    The voice the student picked in settings is honored unless the caller
    passes one explicitly; ignoring it was why "الصوت المفضل" did nothing.
    """
    clean = (text or "").strip()
    if not clean:
        raise ValidationError("لا يوجد نص لنطقه.")
    if len(clean) > settings.ai_voice_max_chars:
        raise ValidationError(
            f"النص أطول من {settings.ai_voice_max_chars} حرفاً — اطلب اللخص أولاً."
        )
    if style not in STYLES:
        raise ValidationError("تعبير الصوت غير معروف.")
    chosen = provider or settings.ai_tts_provider
    if chosen not in TTS_PROVIDERS:
        raise UnsupportedFeatureError(
            f"مزود الصوت «{chosen}» غير مفعّل في هذه البيئة — بدّل AI_TTS_PROVIDER."
        )
    tone = STYLES[style]
    resolved_voice = (voice or _student_voice(db, user) or settings.ai_tts_voice or "system").strip()
    return {
        "provider": chosen,
        "mode": "web_speech",
        "text": clean,
        "voice": resolved_voice,
        "lang": "ar-IQ",
        "style": style,
        "rate": tone["rate"],
        "pitch": tone["pitch"],
        "volume": tone["volume"],
    }


def transcribe(
    audio: bytes | None = None, *, filename: str = "", mime: str = ""
) -> dict[str, Any]:
    """§15/§70 — STT dispatch. The browser provider never uploads audio."""
    chosen = settings.ai_stt_provider
    if chosen == "browser":
        return {
            "provider": "browser",
            "available": False,
            "text": "",
            "hint": "التعرّف على الكلام يجري داخل المتصفح — لا يُرفع أي صوت إلى الخادم.",
        }
    if chosen == "mock":
        if audio and len(audio) > MAX_STT_BYTES:
            raise ValidationError("ملف الصوت أكبر من 8MB.")
        return {
            "provider": "mock",
            "available": True,
            "text": MOCK_TRANSCRIPT,
            "filename": filename,
            "mime": mime or "audio/wav",
        }
    raise UnsupportedFeatureError(
        f"مزوّد التعرّف «{chosen}» غير مفعّل في هذه البيئة — بدّل AI_STT_PROVIDER."
    )


__all__ = [
    "MOCK_TRANSCRIPT",
    "STYLES",
    "speak",
    "transcribe",
    "voice_config",
]

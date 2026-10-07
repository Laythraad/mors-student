"""Voice endpoints (§15 / §70): config, text-to-speech, speech-to-text."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

from ...core.deps import CurrentUser, DbSession
from ...services import voice as voice_service

router = APIRouter(prefix="/voice", tags=["voice"])


class SpeakIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    style: str = Field(default="neutral", max_length=30)
    voice: str | None = Field(default=None, max_length=60)


@router.get("/config")
def config(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    return voice_service.voice_config(db, user)


@router.post("/speak")
def speak(payload: SpeakIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    return voice_service.speak(
        db, user, payload.text, style=payload.style, voice=payload.voice
    )


@router.post("/stt")
async def stt(
    user: CurrentUser,
    audio: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    data: bytes = b""
    filename = ""
    mime = ""
    if audio is not None:
        data = await audio.read()
        filename = audio.filename or ""
        mime = audio.content_type or ""
    return voice_service.transcribe(data, filename=filename, mime=mime)

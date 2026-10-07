"""Chat with Mors — Socratic tutoring with citation gating."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...core.deps import CurrentProfile, DbSession
from ...core.errors import ValidationError
from ...core.rate_limit import enforce_ai
from ...services import chat as service

router = APIRouter(prefix="/chat", tags=["chat"])

MODES = ("tutor", "explain", "socratic", "hint", "quiz", "summarize", "curriculum")


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    subject_id: str | None = None
    lesson_id: str | None = None
    mode: str = Field(default="tutor")
    images: list[str] = Field(default_factory=list, max_length=4)
    book_id: str | None = None
    page_number: int | None = Field(default=None, ge=1, le=100000)
    selection: str = Field(default="", max_length=1500)


class HelpIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    lesson_id: str | None = None
    subject_id: str | None = None


class CreateIn(BaseModel):
    subject_id: str | None = None
    lesson_id: str | None = None
    title: str = Field(default="", max_length=220)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=220)


@router.get("/conversations")
def conversations(profile: CurrentProfile, db: DbSession, limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    return {"conversations": service.list_conversations(db, profile.id, limit=limit)}


@router.post("/conversations")
def create_conversation(payload: CreateIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    row = service.get_or_create_conversation(
        db,
        profile.id,
        subject_id=payload.subject_id,
        lesson_id=payload.lesson_id,
        title=payload.title,
    )
    db.commit()
    return {"id": row.id, "title": row.title}


@router.get("/conversations/{conversation_id}")
def transcript(conversation_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return service.transcript(db, profile.id, conversation_id)


@router.patch("/conversations/{conversation_id}")
def rename(conversation_id: str, payload: RenameIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    service.rename_conversation(db, profile.id, conversation_id, payload.title)
    db.commit()
    return {"ok": True}


@router.delete("/conversations/{conversation_id}")
def archive(conversation_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    service.archive_conversation(db, profile.id, conversation_id)
    db.commit()
    return {"ok": True}


@router.post("/messages")
def message(payload: MessageIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    if payload.mode not in MODES:
        raise ValidationError("وضع محادثة غير معروف.")
    enforce_ai(profile.id)
    result = service.chat(
        db,
        profile.id,
        payload.message,
        conversation_id=payload.conversation_id,
        subject_id=payload.subject_id,
        lesson_id=payload.lesson_id,
        mode=payload.mode,
        images=payload.images,
        book_id=payload.book_id,
        page_number=payload.page_number,
        selection=payload.selection,
    )
    db.commit()
    return result


@router.post("/help")
def help_me(payload: HelpIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    enforce_ai(profile.id)
    result = service.ask_for_help(
        db,
        profile.id,
        question=payload.question,
        lesson_id=payload.lesson_id,
        subject_id=payload.subject_id,
    )
    db.commit()
    return result


__all__ = ["router"]

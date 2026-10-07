"""Library: notes, summaries, flashcards and papers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...core.deps import CurrentProfile, DbSession
from ...core.errors import NotFoundError, ValidationError
from ...services import notes as notes_service
from ...services import papers as papers_service
from ...services.search import index_note

router = APIRouter(prefix="/library", tags=["library"])


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=220)
    body: str = Field(default="", max_length=40000)
    subject_id: str | None = None
    lesson_id: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=10)
    pinned: bool = False


class NotePatch(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None


class SummaryIn(BaseModel):
    lesson_id: str | None = None
    subject_id: str | None = None
    kind: str = Field(default="quick", pattern="^(quick|detailed|exam|corners)$")
    title: str = Field(default="", max_length=220)
    use_ai: bool = True


class CardsIn(BaseModel):
    lesson_id: str
    count: int = Field(default=10, ge=2, le=30)
    use_ai: bool = True


class CardReviewIn(BaseModel):
    quality: int = Field(ge=0, le=5)


class PaperIn(BaseModel):
    title: str = Field(min_length=1, max_length=220)
    kind: str = Field(default="note", pattern="^(note|worksheet|poster|corners|plan)$")
    subject_id: str | None = None
    lesson_id: str | None = None
    emoji: str = Field(default="", max_length=8)
    color: str = Field(default="#2f8ff7", max_length=16)
    tags: list[str] = Field(default_factory=list, max_length=8)


class PaperPatch(BaseModel):
    title: str | None = None
    emoji: str | None = None
    color: str | None = None
    tags: list[str] | None = None
    archived: bool | None = None


class BlocksIn(BaseModel):
    blocks: list[dict[str, Any]] = Field(max_length=60)


class GeneratePaperIn(BaseModel):
    title: str = Field(default="", max_length=220)
    lesson_id: str | None = None
    subject_id: str | None = None
    kind: str = Field(default="worksheet", pattern="^(worksheet|note|corners|poster|plan)$")
    use_ai: bool = True


# --------------------------------------------------------------------------- notes
@router.get("/notes")
def list_notes(
    profile: CurrentProfile,
    db: DbSession,
    subject_id: str | None = None,
    q: str = "",
    pinned: bool = False,
) -> dict[str, Any]:
    return {
        "notes": notes_service.list_notes(
            db, profile.id, subject_id=subject_id, query=q, pinned_only=pinned
        )
    }


@router.post("/notes")
def create_note(payload: NoteIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    note = notes_service.create_note(
        db,
        profile.id,
        title=payload.title,
        body=payload.body,
        subject_id=payload.subject_id,
        lesson_id=payload.lesson_id,
        tags=payload.tags,
        pinned=payload.pinned,
    )
    index_note(db, note)
    db.commit()
    return notes_service.note_payload(note)


@router.get("/notes/{note_id}")
def get_note(note_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    from ...db import Note

    row = db.get(Note, note_id)
    if row is None or row.student_id != profile.id:
        raise NotFoundError("الملاحظة غير موجودة.")
    return notes_service.note_payload(row)


@router.patch("/notes/{note_id}")
def patch_note(note_id: str, payload: NotePatch, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    from ...db import Note

    row = notes_service.update_note(db, profile.id, note_id, payload.model_dump(exclude_none=True))
    if row is not None:
        index_note(db, row)
    db.commit()
    return notes_service.note_payload(row)


@router.delete("/notes/{note_id}")
def delete_note(note_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    notes_service.delete_note(db, profile.id, note_id)
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------------- summaries
@router.get("/summaries")
def list_summaries(profile: CurrentProfile, db: DbSession, lesson_id: str | None = None) -> dict[str, Any]:
    return {"summaries": notes_service.list_summaries(db, profile.id, lesson_id=lesson_id)}


@router.post("/summaries")
def create_summary(payload: SummaryIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    from ...core.rate_limit import enforce_ai

    if payload.use_ai:
        enforce_ai(profile.id)
    result = notes_service.create_summary(
        db,
        profile.id,
        lesson_id=payload.lesson_id,
        subject_id=payload.subject_id,
        kind=payload.kind,
        title=payload.title,
        use_ai=payload.use_ai,
    )
    db.commit()
    return result


# --------------------------------------------------------------------- flashcards
@router.get("/flashcards/due")
def due_cards(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return {"cards": notes_service.due_flashcards(db, profile.id)}


@router.post("/flashcards/generate")
def generate_cards(payload: CardsIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    from ...core.rate_limit import enforce_ai

    if payload.use_ai:
        enforce_ai(profile.id)
    cards = notes_service.flashcards_from_lesson(
        db, profile.id, lesson_id=payload.lesson_id, count=payload.count, use_ai=payload.use_ai
    )
    db.commit()
    return {"cards": cards}


@router.post("/flashcards/{card_id}/review")
def review_card(card_id: str, payload: CardReviewIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = notes_service.review_flashcard(db, profile.id, card_id, payload.quality)
    db.commit()
    return result


# ------------------------------------------------------------------------- papers
@router.get("/papers")
def list_papers(
    profile: CurrentProfile,
    db: DbSession,
    subject_id: str | None = None,
    kind: str | None = None,
    q: str = "",
) -> dict[str, Any]:
    return {
        "papers": papers_service.list_papers(
            db, profile.id, subject_id=subject_id, kind=kind, query=q
        )
    }


@router.post("/papers")
def create_paper(payload: PaperIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    paper = papers_service.create_paper(
        db,
        profile.id,
        title=payload.title,
        kind=payload.kind,
        subject_id=payload.subject_id,
        lesson_id=payload.lesson_id,
        emoji=payload.emoji,
        color=payload.color,
        tags=payload.tags,
    )
    db.commit()
    return papers_service.paper_payload(db, paper)


@router.post("/papers/generate")
def generate_paper(payload: GeneratePaperIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    from ...core.rate_limit import enforce_ai

    if payload.use_ai:
        enforce_ai(profile.id)
    result = papers_service.generate_paper(
        db,
        profile.id,
        title=payload.title,
        lesson_id=payload.lesson_id,
        subject_id=payload.subject_id,
        kind=payload.kind,
        use_ai=payload.use_ai,
    )
    db.commit()
    return result


@router.get("/papers/{paper_id}")
def get_paper(paper_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    paper = papers_service._owned(db, profile.id, paper_id)
    return papers_service.paper_payload(db, paper)


@router.patch("/papers/{paper_id}")
def patch_paper(paper_id: str, payload: PaperPatch, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    paper = papers_service.update_paper(db, profile.id, paper_id, payload.model_dump(exclude_none=True))
    db.commit()
    return papers_service.paper_payload(db, paper)


@router.delete("/papers/{paper_id}")
def delete_paper(paper_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    papers_service.delete_paper(db, profile.id, paper_id)
    db.commit()
    return {"ok": True}


@router.put("/pages/{page_id}/blocks")
def save_blocks(page_id: str, payload: BlocksIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    pages = papers_service.save_blocks(db, profile.id, page_id=page_id, blocks=payload.blocks)
    db.commit()
    return {"pages": pages}


@router.post("/papers/{paper_id}/pages")
def add_page(paper_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    page = papers_service.add_page(db, profile.id, paper_id)
    db.commit()
    return page


__all__ = ["router"]

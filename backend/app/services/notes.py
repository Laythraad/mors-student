"""Notes, summaries and flashcards — the student's own knowledge layer.

Summaries and flashcards are AI-assisted but never AI-dependent: the local
fallback derives them from the lesson's objectives so the feature works with
no API key and no invented curriculum.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..ai import AIRequest, ask, chunks_to_context, lesson_context, retrieve
from ..config import settings
from ..core.errors import NotFoundError, ValidationError
from ..db import (
    Flashcard,
    Lesson,
    Note,
    Summary,
    utcnow,
)
from ..mors import EventType, bus


# --------------------------------------------------------------------------- #
# notes
# --------------------------------------------------------------------------- #
def create_note(
    db: Session,
    student_id: str,
    *,
    title: str,
    body: str = "",
    subject_id: str | None = None,
    lesson_id: str | None = None,
    tags: list[str] | None = None,
    pinned: bool = False,
) -> Note:
    title = (title or "").strip()
    if not title:
        raise ValidationError("عنوان الملاحظة مطلوب.")
    row = Note(
        student_id=student_id,
        title=title[:220],
        body=body or "",
        subject_id=subject_id,
        lesson_id=lesson_id,
        tags=[str(t) for t in (tags or [])][:10],
        pinned=pinned,
    )
    db.add(row)
    db.flush()
    return row


def update_note(db: Session, student_id: str, note_id: str, data: dict[str, Any]) -> Note:
    row = _owned_note(db, student_id, note_id)
    if "title" in data:
        row.title = str(data["title"]).strip()[:220] or row.title
    if "body" in data:
        row.body = str(data["body"])
    if "tags" in data:
        row.tags = [str(t) for t in (data["tags"] or [])][:10]
    if "pinned" in data:
        row.pinned = bool(data["pinned"])
    db.flush()
    return row


def delete_note(db: Session, student_id: str, note_id: str) -> bool:
    row = _owned_note(db, student_id, note_id)
    db.delete(row)
    db.flush()
    return True


def _owned_note(db: Session, student_id: str, note_id: str) -> Note:
    row = db.get(Note, note_id)
    if row is None or row.student_id != student_id:
        raise NotFoundError("الملاحظة غير موجودة.")
    return row


def list_notes(
    db: Session,
    student_id: str,
    *,
    subject_id: str | None = None,
    query: str = "",
    pinned_only: bool = False,
    limit: int = 60,
) -> list[dict[str, Any]]:
    q = db.query(Note).filter(Note.student_id == student_id)
    if subject_id:
        q = q.filter(Note.subject_id == subject_id)
    if pinned_only:
        q = q.filter(Note.pinned.is_(True))
    if query:
        like = f"%{query.strip()}%"
        q = q.filter(or_(Note.title.like(like), Note.body.like(like)))
    rows = q.order_by(Note.pinned.desc(), Note.updated_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "body": r.body,
            "subject_id": r.subject_id,
            "lesson_id": r.lesson_id,
            "tags": r.tags or [],
            "pinned": r.pinned,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


def note_payload(row: Note) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "subject_id": row.subject_id,
        "lesson_id": row.lesson_id,
        "tags": row.tags or [],
        "pinned": row.pinned,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# --------------------------------------------------------------------------- #
# summaries
# --------------------------------------------------------------------------- #
def _local_summary(lesson: Lesson | None) -> dict[str, Any]:
    if lesson is None:
        return {"title": "", "body": "", "bullets": []}
    objectives = [str(o) for o in (lesson.objectives or []) if o]
    body = "\n".join(
        filter(
            None,
            [
                lesson.summary or "",
                ("الأهداف:\n" + "\n".join(f"• {o}" for o in objectives)) if objectives else "",
                ("المصطلحات: " + ", ".join(str(k) for k in (lesson.keywords or []) if k))
                if (lesson.keywords or [])
                else "",
            ],
        )
    )
    return {
        "title": f"ملخص {lesson.title}",
        "body": body,
        "bullets": objectives,
        "source": "curriculum",
    }


def create_summary(
    db: Session,
    student_id: str,
    *,
    lesson_id: str | None = None,
    subject_id: str | None = None,
    kind: str = "quick",
    title: str = "",
    use_ai: bool = True,
) -> dict[str, Any]:
    lesson = db.get(Lesson, lesson_id) if lesson_id else None
    if lesson and not subject_id:
        subject_id = lesson.subject_id

    fallback = _local_summary(lesson)
    data = fallback
    source_ids: list[str] = []

    if use_ai:
        chunks = retrieve(
            db,
            (lesson.title if lesson else title) or "",
            student_id=student_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
            top_k=settings.rag_top_k,
        )
        source_ids = [str(c.get("source_id") or c.get("chunk_id") or "") for c in chunks]
        try:
            answer = ask(
                db,
                AIRequest(
                    task="summarize",
                    input=lesson.title if lesson else title,
                    student_id=student_id,
                    subject_id=subject_id,
                    lesson_id=lesson_id,
                    context={
                        "الدرس": lesson_context(db, lesson_id),
                        "مصدر": chunks_to_context(chunks),
                    },
                    constraints="لا تخترع معلومات. ألّف من السياق فقط.",
                    want_json=True,
                    max_tokens=900,
                ),
            )
            if isinstance(answer.data, dict) and (answer.data.get("body") or answer.data.get("bullets")):
                data = {
                    "title": str(answer.data.get("title") or fallback["title"]),
                    "body": str(answer.data.get("body") or ""),
                    "bullets": [str(b) for b in (answer.data.get("bullets") or [])][:8],
                    "source": "ai",
                }
        except Exception:  # noqa: BLE001 - local summary is always available
            data = fallback

    if not data.get("body"):
        raise ValidationError("تعذّر إنشاء الملخص لهذا الدرس.")

    summary = Summary(
        student_id=student_id,
        subject_id=subject_id,
        lesson_id=lesson_id,
        kind=kind,
        title=title or data.get("title") or (lesson.title if lesson else "ملخص"),
        body=data["body"],
        source_ids=[s for s in source_ids if s][:10],
    )
    db.add(summary)
    db.flush()
    bus.emit(
        db,
        student_id,
        EventType.SUMMARY_CREATED,
        {"summary_id": summary.id, "lesson_id": lesson_id, "subject_id": subject_id},
    )
    return summary_payload(summary)


def summary_payload(row: Summary) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "kind": row.kind,
        "subject_id": row.subject_id,
        "lesson_id": row.lesson_id,
        "source_ids": row.source_ids or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_summaries(
    db: Session, student_id: str, *, lesson_id: str | None = None, limit: int = 40
) -> list[dict[str, Any]]:
    q = db.query(Summary).filter(Summary.student_id == student_id)
    if lesson_id:
        q = q.filter(Summary.lesson_id == lesson_id)
    rows = q.order_by(Summary.created_at.desc()).limit(limit).all()
    return [summary_payload(r) for r in rows]


# --------------------------------------------------------------------------- #
# flashcards
# --------------------------------------------------------------------------- #
def _local_cards(lesson: Lesson | None) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    if lesson is None:
        return cards
    for objective in [str(o) for o in (lesson.objectives or []) if o][:8]:
        cards.append({"front": f"ما المقصود بـ: {objective}؟", "back": objective})
    for keyword in [str(k) for k in (lesson.keywords or []) if k][:6]:
        cards.append({"front": f"عرّف: {keyword}", "back": keyword})
    return cards


def flashcards_from_lesson(
    db: Session,
    student_id: str,
    *,
    lesson_id: str,
    count: int = 10,
    use_ai: bool = True,
) -> list[dict[str, Any]]:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise NotFoundError("الدرس غير موجود.")

    cards = _local_cards(lesson)
    if use_ai:
        chunks = retrieve(
            db, lesson.title, student_id=student_id, lesson_id=lesson_id, top_k=settings.rag_top_k
        )
        try:
            answer = ask(
                db,
                AIRequest(
                    task="quiz",
                    input=f"حوّل هذا الدرس إلى {count} بطاقات تكرار: {lesson.title}",
                    student_id=student_id,
                    lesson_id=lesson_id,
                    context={"الدرس": lesson_context(db, lesson_id), "مصدر": chunks_to_context(chunks)},
                    constraints="بطاقة سؤال/جواب قصير. لا تخترع معلومات.",
                    schema='{"cards":[{"front":"...","back":"..."}]}',
                    want_json=True,
                    max_tokens=1200,
                ),
            )
            raw = (answer.data or {}).get("cards") if isinstance(answer.data, dict) else None
            if isinstance(raw, list) and raw:
                cards = [
                    {"front": str(c.get("front", "")), "back": str(c.get("back", ""))}
                    for c in raw
                    if isinstance(c, dict) and c.get("front") and c.get("back")
                ][:count]
        except Exception:  # noqa: BLE001
            pass

    created: list[dict[str, Any]] = []
    for card in cards[:count]:
        row = Flashcard(
            student_id=student_id,
            subject_id=lesson.subject_id,
            lesson_id=lesson_id,
            front=card["front"][:500],
            back=card["back"][:500],
            due_at=utcnow(),
        )
        db.add(row)
        db.flush()
        created.append(flashcard_payload(row))
    return created


def flashcard_payload(row: Flashcard) -> dict[str, Any]:
    return {
        "id": row.id,
        "front": row.front,
        "back": row.back,
        "lesson_id": row.lesson_id,
        "subject_id": row.subject_id,
        "ease": row.ease,
        "interval_days": row.interval_days,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "reps": row.reps,
        "lapses": row.lapses,
    }


def due_flashcards(db: Session, student_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    now = utcnow()
    rows = (
        db.query(Flashcard)
        .filter(Flashcard.student_id == student_id, Flashcard.due_at <= now)
        .order_by(Flashcard.due_at)
        .limit(limit)
        .all()
    )
    return [flashcard_payload(r) for r in rows]


def review_flashcard(db: Session, student_id: str, card_id: str, quality: int) -> dict[str, Any]:
    """SM-2 lite: 0 forgot … 5 easy."""
    row = db.get(Flashcard, card_id)
    if row is None or row.student_id != student_id:
        raise NotFoundError("البطاقة غير موجودة.")
    quality = max(0, min(5, int(quality)))
    if quality < 3:
        row.lapses = (row.lapses or 0) + 1
        row.interval_days = 1.0
        row.ease = max(1.3, (row.ease or 2.5) - 0.2)
    else:
        row.reps = (row.reps or 0) + 1
        row.ease = min(3.2, (row.ease or 2.5) + 0.05)
        row.interval_days = round(min(180.0, max(1.0, (row.interval_days or 1.0) * row.ease)), 2)
    row.due_at = utcnow() + timedelta(days=row.interval_days)
    db.flush()
    return flashcard_payload(row)


__all__ = [
    "create_note",
    "update_note",
    "delete_note",
    "list_notes",
    "note_payload",
    "create_summary",
    "summary_payload",
    "list_summaries",
    "flashcards_from_lesson",
    "flashcard_payload",
    "due_flashcards",
    "review_flashcard",
]

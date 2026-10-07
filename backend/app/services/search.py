"""Global search across everything a student owns, plus the curriculum.

Grouped by kind so the UI can render sections; RAG chunks come last because
they are the least predictable.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..db import Lesson, Note, Paper, Upload, Video
from ..rag import hybrid_search

GROUPS = ("lessons", "notes", "papers", "uploads", "videos", "sources")


def _row(row: Any, *, group: str, title: str, body: str = "", **extra: Any) -> dict[str, Any]:
    payload = {"group": group, "id": getattr(row, "id", ""), "title": title, "body": body}
    payload.update(extra)
    return payload


def global_search(
    db: Session,
    student_id: str,
    query: str,
    *,
    kind: str = "all",
    subject_id: str | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    started = time.perf_counter()
    text = (query or "").strip()
    if not text:
        return {"query": "", "groups": {g: [] for g in GROUPS}, "total": 0, "took_ms": 0}

    like = f"%{text}%"
    wanted = set(GROUPS) if kind == "all" else {kind}
    groups: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUPS}

    if "lessons" in wanted:
        q = db.query(Lesson).filter(or_(Lesson.title.like(like), Lesson.summary.like(like)))
        if subject_id:
            q = q.filter(Lesson.subject_id == subject_id)
        matches = q.order_by(Lesson.index).limit(limit * 3).all()
        matched = [
            row
            for row in matches
            if any(text in str(k) for k in (row.keywords or []))
            or row in matches[:limit]
        ][:limit]
        for row in matched:
            groups["lessons"].append(
                _row(
                    row,
                    group="lessons",
                    title=row.title,
                    body=(row.summary or "")[:240],
                    subject_id=row.subject_id,
                    link=f"/lesson/{row.id}",
                )
            )

    if "notes" in wanted:
        q = db.query(Note).filter(
            Note.student_id == student_id, or_(Note.title.like(like), Note.body.like(like))
        )
        for row in q.order_by(Note.updated_at.desc()).limit(limit).all():
            groups["notes"].append(
                _row(
                    row,
                    group="notes",
                    title=row.title,
                    body=(row.body or "")[:240],
                    link=f"/notes/{row.id}",
                )
            )

    if "papers" in wanted:
        q = db.query(Paper).filter(Paper.student_id == student_id, Paper.title.like(like))
        for row in q.order_by(Paper.updated_at.desc()).limit(limit).all():
            groups["papers"].append(
                _row(row, group="papers", title=row.title, link=f"/papers/{row.id}", emoji=row.emoji)
            )

    if "uploads" in wanted:
        q = db.query(Upload).filter(
            Upload.student_id == student_id,
            or_(Upload.filename.like(like), Upload.extracted_text.like(like)),
        )
        for row in q.order_by(Upload.created_at.desc()).limit(limit).all():
            groups["uploads"].append(
                _row(
                    row,
                    group="uploads",
                    title=row.filename,
                    body=(row.extracted_text or "")[:240],
                    link=f"/uploads/{row.id}",
                    status=row.status,
                )
            )

    if "videos" in wanted:
        q = db.query(Video).filter(
            or_(Video.title.like(like), Video.description.like(like), Video.transcript.like(like))
        )
        if subject_id:
            q = q.filter(Video.subject_id == subject_id)
        for row in q.order_by(Video.position).limit(limit).all():
            groups["videos"].append(
                _row(
                    row,
                    group="videos",
                    title=row.title,
                    body=(row.description or "")[:200],
                    link=f"/videos/{row.id}",
                    duration=row.duration_seconds,
                )
            )

    if "sources" in wanted:
        try:
            hits = hybrid_search(
                db, text, student_id=student_id, subject_id=subject_id, top_k=limit
            )
        except Exception:  # noqa: BLE001 - search must never 500
            hits = []
        for hit in hits:
            groups["sources"].append(
                {
                    "group": "sources",
                    "id": hit.get("chunk_id", ""),
                    "title": hit.get("citation") or hit.get("title") or "",
                    "body": (hit.get("text") or "")[:300],
                    "score": round(float(hit.get("score", 0.0)), 3),
                    "source_id": hit.get("source_id"),
                    "lesson_id": hit.get("lesson_id"),
                    "link": f"/lesson/{hit['lesson_id']}" if hit.get("lesson_id") else "",
                }
            )

    total = sum(len(v) for v in groups.values())
    return {
        "query": text,
        "groups": groups,
        "total": total,
        "took_ms": int((time.perf_counter() - started) * 1000),
    }


def index_note(db: Session, note: Note) -> None:
    """Mirror a note into SearchDocument so it survives a full-text fallback."""
    from ..db import SearchDocument

    row = (
        db.query(SearchDocument)
        .filter(
            SearchDocument.entity_type == "note",
            SearchDocument.entity_id == note.id,
        )
        .first()
    )
    if row is None:
        row = SearchDocument(
            entity_type="note", entity_id=note.id, student_id=note.student_id
        )
        db.add(row)
    row.title = note.title
    row.body = note.body or ""
    row.subject_id = note.subject_id
    row.lesson_id = note.lesson_id
    row.url = f"/notes/{note.id}"
    db.flush()


__all__ = ["global_search", "index_note", "GROUPS"]

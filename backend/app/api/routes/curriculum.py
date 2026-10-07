"""Curriculum browsing: stages → branches → subjects → units → lessons."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ...core.deps import DbSession, OptionalUser
from ...core.errors import NotFoundError
from ...db import Lesson, StudentProfile
from ...services import curriculum as service

router = APIRouter(prefix="/curriculum", tags=["curriculum"])


@router.get("/stages")
def stages(db: DbSession) -> dict[str, Any]:
    return {"stages": service.list_stages(db)}


@router.get("/branches")
def branches(db: DbSession, stage_id: str = Query(...)) -> dict[str, Any]:
    return {"branches": service.list_branches(db, stage_id)}


@router.get("/subjects")
def subjects(
    db: DbSession,
    branch_id: str | None = None,
    stage_id: str | None = None,
) -> dict[str, Any]:
    return {"subjects": service.list_subjects(db, branch_id=branch_id, stage_id=stage_id)}


@router.get("/mine")
def mine(db: DbSession, user: OptionalUser) -> dict[str, Any]:
    if user is None:
        return {"subjects": []}
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).one_or_none()
    if profile is None:
        return {"subjects": []}
    return {"subjects": service.subjects_for_student(db, profile.id)}


@router.get("/subjects/{subject_id}/tree")
def subject_tree(subject_id: str, db: DbSession) -> dict[str, Any]:
    chapters = service.subject_tree(db, subject_id)
    if not chapters:
        raise NotFoundError("المادة غير موجودة.")
    return {"chapters": chapters}


@router.get("/lessons/{lesson_id}")
def lesson(lesson_id: str, db: DbSession, with_pages: bool = False) -> dict[str, Any]:
    lesson_row = service.get_lesson(db, lesson_id, with_pages=with_pages)
    if lesson_row is None:
        raise NotFoundError("الدرس غير موجود.")
    return lesson_row


@router.get("/search")
def search(
    db: DbSession,
    q: str = Query("", max_length=200),
    subject_id: str | None = None,
    limit: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    rows = service.search_lessons(db, q, subject_id=subject_id, limit=limit)
    return {"results": rows, "query": q}


@router.get("/next-lessons")
def next_lessons(
    db: DbSession,
    user: OptionalUser,
    subject_id: str | None = None,
    limit: int = Query(6, ge=1, le=20),
) -> dict[str, Any]:
    """Curriculum-ordered lessons a student has not touched yet."""
    from ...db import MasteryScore, StudentSubject, Subject

    if user is None:
        return {"lessons": []}
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).one_or_none()
    if profile is None:
        return {"lessons": []}

    subject_ids = [subject_id] if subject_id else [
        r.subject_id
        for r in db.query(StudentSubject)
        .filter(StudentSubject.profile_id == profile.id, StudentSubject.is_active.is_(True))
        .all()
    ]
    if not subject_ids:
        return {"lessons": []}

    mastered = {
        row.lesson_id
        for row in db.query(MasteryScore)
        .filter(
            MasteryScore.student_id == profile.id,
            MasteryScore.lesson_id.isnot(None),
            MasteryScore.score >= 85,
        )
        .all()
    }
    rows = (
        db.query(Lesson)
        .filter(Lesson.subject_id.in_(subject_ids))
        .order_by(Lesson.subject_id, Lesson.index)
        .all()
    )
    pending = [r for r in rows if r.id not in mastered][:limit]
    subjects = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()}
    return {
        "lessons": [
            {
                "id": r.id,
                "title": r.title,
                "summary": (r.summary or "")[:200],
                "subject_id": r.subject_id,
                "subject": subjects[r.subject_id].name_ar if r.subject_id in subjects else "",
                "estimated_minutes": r.estimated_minutes,
                "difficulty": r.difficulty,
            }
            for r in pending
        ]
    }


__all__ = ["router"]

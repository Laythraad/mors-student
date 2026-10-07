"""Curriculum access — stages → branches → subjects → chapters → lessons.

The frontend never hard-codes the syllabus; it asks for whatever the current
stage/branch actually contains, which is what keeps the platform ready for
الثالث المتوسط … السادس and every branch beyond الرابع.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from ..core.errors import NotFoundError
from ..db import (
    Branch,
    Book,
    Chapter,
    Lesson,
    Source,
    Stage,
    StudentSubject,
    Subject,
    Unit,
)


def list_stages(db: Session, *, active_only: bool = True) -> list[dict[str, Any]]:
    q = db.query(Stage)
    if active_only:
        q = q.filter(Stage.is_active.is_(True))
    return [
        {
            "id": s.id,
            "code": s.code,
            "name_ar": s.name_ar,
            "name_en": s.name_en,
            "is_demo": s.is_demo,
            "branches": [
                {
                    "id": b.id,
                    "code": b.code,
                    "name_ar": b.name_ar,
                    "track": b.track,
                    "is_demo": b.is_demo,
                }
                for b in sorted(s.branches, key=lambda x: x.sort_order)
                if b.is_active
            ],
        }
        for s in sorted(q.all(), key=lambda x: x.sort_order)
    ]


def list_branches(db: Session, stage_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(Branch)
        .filter(Branch.stage_id == stage_id, Branch.is_active.is_(True))
        .order_by(Branch.sort_order)
        .all()
    )
    return [
        {"id": b.id, "code": b.code, "name_ar": b.name_ar, "track": b.track, "is_demo": b.is_demo}
        for b in rows
    ]


def list_subjects(db: Session, *, branch_id: str | None = None, stage_id: str | None = None) -> list[dict[str, Any]]:
    q = db.query(Subject).filter(Subject.is_active.is_(True))
    if branch_id:
        q = q.filter(Subject.branch_id == branch_id)
    elif stage_id:
        branch_ids = [b.id for b in db.query(Branch).filter(Branch.stage_id == stage_id)]
        q = q.filter(Subject.branch_id.in_(branch_ids)) if branch_ids else q.filter(False)
    rows = q.order_by(Subject.sort_order).all()
    return [
        {
            "id": s.id,
            "code": s.code,
            "name_ar": s.name_ar,
            "name_en": s.name_en,
            "color": s.color,
            "icon": s.icon,
            "branch_id": s.branch_id,
            "is_demo": s.is_demo,
        }
        for s in rows
    ]


def subjects_for_student(db: Session, profile_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(Subject, StudentSubject)
        .join(StudentSubject, StudentSubject.subject_id == Subject.id)
        .filter(StudentSubject.profile_id == profile_id, StudentSubject.is_active.is_(True))
        .order_by(Subject.sort_order)
        .all()
    )
    return [
        {
            "id": subject.id,
            "code": subject.code,
            "name_ar": subject.name_ar,
            "color": subject.color,
            "icon": subject.icon,
            "priority": link.priority,
        }
        for subject, link in rows
    ]


def lesson_brief(lesson: Lesson) -> dict[str, Any]:
    return {
        "id": lesson.id,
        "title": lesson.title,
        "summary": lesson.summary,
        "index": lesson.index,
        "difficulty": lesson.difficulty,
        "estimated_minutes": lesson.estimated_minutes,
        "page_start": lesson.page_start,
        "page_end": lesson.page_end,
        "objectives": lesson.objectives,
        "keywords": lesson.keywords,
        "subject_id": lesson.subject_id,
        "chapter_id": lesson.chapter_id,
        "source_id": lesson.source_id,
        "is_demo": lesson.is_demo,
    }


def subject_tree(db: Session, subject_id: str) -> list[dict[str, Any]]:
    """Chapters → units → lessons for one subject."""
    book_ids = [b.id for b in db.query(Book).filter(Book.subject_id == subject_id)]
    if not book_ids:
        lessons = (
            db.query(Lesson)
            .filter(Lesson.subject_id == subject_id)
            .order_by(Lesson.index)
            .all()
        )
        return [
            {
                "id": None,
                "title": "الدروس",
                "units": [{"id": None, "title": "", "lessons": [lesson_brief(l) for l in lessons]}],
            }
        ]

    chapters = (
        db.query(Chapter)
        .filter(Chapter.book_id.in_(book_ids))
        .order_by(Chapter.index)
        .all()
    )
    tree: list[dict[str, Any]] = []
    for chapter in chapters:
        units = (
            db.query(Unit).filter(Unit.chapter_id == chapter.id).order_by(Unit.index).all()
        )
        unit_payload = []
        for unit in units:
            lessons = (
                db.query(Lesson)
                .filter(Lesson.unit_id == unit.id)
                .order_by(Lesson.index)
                .all()
            )
            unit_payload.append(
                {"id": unit.id, "title": unit.title, "lessons": [lesson_brief(l) for l in lessons]}
            )
        if not unit_payload:
            lessons = (
                db.query(Lesson)
                .filter(Lesson.chapter_id == chapter.id)
                .order_by(Lesson.index)
                .all()
            )
            if lessons:
                unit_payload.append(
                    {"id": None, "title": "", "lessons": [lesson_brief(l) for l in lessons]}
                )
        tree.append(
            {
                "id": chapter.id,
                "title": chapter.title,
                "index": chapter.index,
                "page_start": chapter.page_start,
                "page_end": chapter.page_end,
                "units": unit_payload,
            }
        )
    return tree


def get_lesson(db: Session, lesson_id: str, *, with_pages: bool = False) -> dict[str, Any]:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise NotFoundError("الدرس غير موجود.")
    payload = lesson_brief(lesson)
    subject = db.get(Subject, lesson.subject_id)
    payload["subject"] = {"id": subject.id, "name_ar": subject.name_ar, "color": subject.color} if subject else None
    if lesson.chapter_id:
        chapter = db.get(Chapter, lesson.chapter_id)
        payload["chapter"] = {"id": chapter.id, "title": chapter.title} if chapter else None
    if lesson.unit_id:
        unit = db.get(Unit, lesson.unit_id)
        payload["unit"] = {"id": unit.id, "title": unit.title} if unit else None
    if lesson.source_id:
        source = db.get(Source, lesson.source_id)
        payload["source"] = {
            "id": source.id,
            "citation": source.citation,
            "page": source.page_number,
            "kind": source.kind,
        } if source else None
    if with_pages:
        payload["pages"] = [
            {"page_number": p.page_number, "text": p.text} for p in lesson.pages
        ]
    payload["prerequisites"] = lesson.prerequisites
    return payload


def search_lessons(db: Session, query: str, *, subject_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    q = db.query(Lesson)
    if subject_id:
        q = q.filter(Lesson.subject_id == subject_id)
    term = f"%{query.strip()}%"
    rows = q.filter(
        (Lesson.title.ilike(term))
        | (Lesson.summary.ilike(term))
        | (cast(Lesson.keywords, String).ilike(term))
    ).limit(limit).all()
    return [lesson_brief(r) for r in rows]


def get_subject(db: Session, subject_id: str) -> Subject:
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise NotFoundError("المادة غير موجودة.")
    return subject


__all__ = [
    "list_stages",
    "list_branches",
    "list_subjects",
    "subjects_for_student",
    "subject_tree",
    "get_lesson",
    "search_lessons",
    "get_subject",
    "lesson_brief",
]

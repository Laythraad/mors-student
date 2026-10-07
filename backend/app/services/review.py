"""Spaced repetition — the review schedule the plan is built on.

A simplified SM-2: intervals grow while the student keeps getting it right,
and collapse the moment they don't. Mastery ≥ 85 slows the cadence down;
repeated failure pushes the topic into `weak_topics` instead of silently
scheduling it forever.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..db import Lesson, Review, Subject, utcnow
from .progress import MASTERY_STRONG, MASTERY_WEAK, active_weak, register_weak, update_mastery

MIN_INTERVAL = 0.5
MAX_INTERVAL = 120


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalise to naive UTC so it can be compared with `utcnow()`.

    SQLite drops the offset on round-trip, and `utcnow()` is naive UTC, so an
    offset-aware value here would crash the arithmetic.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        from datetime import timezone as _tz

        return value.astimezone(_tz.utc).replace(tzinfo=None)
    return value


def _next_interval(current: float, ease: float, quality: int, mastery: float) -> tuple[float, float]:
    """Return (interval_days, ease). quality: 0..5."""
    ease = ease or 2.5
    if quality >= 4:
        multiplier = ease
        if mastery >= MASTERY_STRONG:
            multiplier *= 1.4  # mastered — back off
        interval = max(MIN_INTERVAL, current) * multiplier
        ease = min(3.2, ease + 0.08)
    elif quality == 3:
        interval = max(MIN_INTERVAL, current) * 1.1
    else:
        interval = MIN_INTERVAL
        ease = max(1.3, ease - 0.22)
    return min(MAX_INTERVAL, round(interval, 2)), round(ease, 3)


def schedule_review(
    db: Session,
    student_id: str,
    *,
    lesson_id: str | None = None,
    subject_id: str | None = None,
    topic: str = "",
    quality: int = 3,
    due_in_days: float | None = None,
    source: str = "auto",
) -> Review:
    conditions = [Review.student_id == student_id, Review.status != "done"]
    if lesson_id:
        conditions.append(Review.lesson_id == lesson_id)
    elif topic:
        conditions.append(Review.topic == topic)
    else:
        conditions.append(Review.lesson_id.is_(None))
    row = db.query(Review).filter(*conditions).first()
    mastery_row = update_mastery(
        db,
        student_id,
        subject_id=subject_id,
        lesson_id=lesson_id,
        topic=topic,
        correct=quality >= 3,
    )

    if row is None:
        interval = due_in_days if due_in_days is not None else 1.0
        row = Review(
            student_id=student_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
            topic=topic,
            due_at=utcnow() + timedelta(days=interval),
            interval_days=interval,
            ease=2.5,
            reps=1 if quality >= 3 else 0,
            lapses=0 if quality >= 3 else 1,
            last_result=_quality_label(quality),
            status="scheduled",
            source=source,
        )
        db.add(row)
        db.flush()
        return row

    if due_in_days is not None:
        interval = due_in_days
        ease = row.ease
    else:
        interval, ease = _next_interval(row.interval_days or 1.0, row.ease, quality, mastery_row.score)
    row.interval_days = interval
    row.ease = ease
    row.due_at = utcnow() + timedelta(days=interval)
    row.last_result = _quality_label(quality)
    row.reps = (row.reps or 0) + (1 if quality >= 3 else 0)
    if quality < 3:
        row.lapses = (row.lapses or 0) + 1
        row.status = "due"
    else:
        row.status = "scheduled"
    db.flush()
    return row


def _quality_label(quality: int) -> str:
    if quality >= 5:
        return "easy"
    if quality >= 4:
        return "good"
    if quality >= 3:
        return "ok"
    if quality >= 1:
        return "hard"
    return "forgot"


def due_reviews(db: Session, student_id: str, *, limit: int = 20, horizon_days: int = 7) -> list[dict[str, Any]]:
    now = utcnow()
    horizon = now + timedelta(days=horizon_days)
    rows = (
        db.query(Review)
        .filter(
            Review.student_id == student_id,
            Review.status != "done",
            Review.due_at <= horizon,
        )
        .order_by(Review.due_at)
        .limit(limit)
        .all()
    )
    out = []
    for row in rows:
        lesson = db.get(Lesson, row.lesson_id) if row.lesson_id else None
        subject = db.get(Subject, row.subject_id) if row.subject_id else None
        out.append(
            {
                "id": row.id,
                "topic": row.topic or (lesson.title if lesson else ""),
                "lesson_id": row.lesson_id,
                "subject_id": row.subject_id,
                "subject": subject.name_ar if subject else "",
                "due_at": row.due_at.isoformat() if row.due_at else None,
                "overdue": bool(_as_utc(row.due_at) and _as_utc(row.due_at) < now),
                "interval_days": row.interval_days,
                "status": row.status,
            }
        )
    return out


def complete_review(db: Session, student_id: str, review_id: str, quality: int) -> dict[str, Any]:
    row = db.get(Review, review_id)
    if row is None or row.student_id != student_id:
        return {"ok": False}
    schedule_review(
        db,
        student_id,
        lesson_id=row.lesson_id,
        subject_id=row.subject_id,
        topic=row.topic,
        quality=quality,
    )
    db.delete(row)
    db.flush()
    return {"ok": True, "quality": _quality_label(quality)}


def review_pressure(db: Session, student_id: str) -> dict[str, Any]:
    """How much review work is waiting — used by the planner."""
    now = utcnow()
    overdue = (
        db.query(Review)
        .filter(Review.student_id == student_id, Review.status != "done")
        .all()
    )
    overdue_count = sum(1 for r in overdue if _as_utc(r.due_at) and _as_utc(r.due_at) < now)
    horizon = now + timedelta(days=3)
    upcoming = sum(
        1
        for r in overdue
        if _as_utc(r.due_at) and now <= _as_utc(r.due_at) <= horizon
    )
    weak = active_weak(db, student_id, 8)
    return {
        "overdue": overdue_count,
        "upcoming": upcoming,
        "weak_count": len(weak),
        "weak_topics": [w.topic for w in weak],
        "load": overdue_count + upcoming + len(weak),
    }


__all__ = ["schedule_review", "due_reviews", "complete_review", "review_pressure"]

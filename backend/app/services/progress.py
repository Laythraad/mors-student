"""Mastery, weak-topic detection, streaks, achievements and progress reports.

Mastery is an exponentially-weighted moving average over *attempts*, not a
raw percentage: a single lucky quiz cannot flip a topic from red to green,
and a slow recovery after a bad week is visible as a trend rather than a
hidden reset.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..db import (
    Achievement,
    CalendarEvent,
    Lesson,
    MasteryScore,
    QuizAttempt,
    Source,
    Stage,
    StudentAchievement,
    StudentProfile,
    StudySession,
    StudyStreak,
    Subject,
    Task,
    WeakTopic,
    utcnow,
)
from ..mors import EventType, PersonalityContext, bus, react
from ..mors.models_helper import queue_message, record_state

ALPHA = 0.35          # weight of the newest observation
MASTERY_WEAK = 55     # below this a topic is "weak"
MASTERY_STRONG = 85   # above this repeated review is reduced


# --------------------------------------------------------------------------- #
# mastery
# --------------------------------------------------------------------------- #
def get_mastery(
    db: Session,
    student_id: str,
    *,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    topic: str | None = None,
) -> MasteryScore | None:
    """One row per lesson (uq_mastery_lesson). ``topic`` only narrows the
    search for standalone topic rows, where ``lesson_id`` is NULL."""
    q = db.query(MasteryScore).filter(MasteryScore.student_id == student_id)
    if subject_id:
        q = q.filter(MasteryScore.subject_id == subject_id)
    if lesson_id:
        q = q.filter(MasteryScore.lesson_id == lesson_id)
    elif topic:
        q = q.filter(MasteryScore.topic == topic)
    return q.first()


def update_mastery(
    db: Session,
    student_id: str,
    *,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    topic: str = "",
    correct: bool,
    weight: float = 1.0,
) -> MasteryScore:
    row = get_mastery(db, student_id, subject_id=subject_id, lesson_id=lesson_id, topic=topic)
    observation = 100.0 if correct else 35.0
    if row is None:
        row = MasteryScore(
            student_id=student_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
            topic=topic or "",
            score=observation,
            samples=1,
            correct=1 if correct else 0,
            wrong=0 if correct else 1,
            last_practiced_at=utcnow(),
        )
        db.add(row)
        db.flush()
        return row

    previous = row.score
    blended = ALPHA * weight * observation + (1 - ALPHA * weight) * previous
    row.trend = blended - previous
    row.score = max(0.0, min(100.0, blended))
    row.samples = (row.samples or 0) + 1
    row.correct = (row.correct or 0) + (1 if correct else 0)
    row.wrong = (row.wrong or 0) + (0 if correct else 1)
    row.last_practiced_at = utcnow()
    db.flush()
    return row


def mastery_map(db: Session, student_id: str, subject_id: str | None = None) -> list[dict[str, Any]]:
    q = db.query(MasteryScore).filter(MasteryScore.student_id == student_id)
    if subject_id:
        q = q.filter(MasteryScore.subject_id == subject_id)
    rows = q.order_by(MasteryScore.score.asc()).all()
    out = []
    for row in rows:
        lesson = db.get(Lesson, row.lesson_id) if row.lesson_id else None
        out.append(
            {
                "lesson_id": row.lesson_id,
                "subject_id": row.subject_id,
                "topic": row.topic or (lesson.title if lesson else ""),
                "score": round(row.score, 1),
                "trend": round(row.trend, 1),
                "samples": row.samples,
                "state": "weak" if row.score < MASTERY_WEAK else ("strong" if row.score >= MASTERY_STRONG else "ok"),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# weak topics
# --------------------------------------------------------------------------- #
def register_weak(
    db: Session,
    student_id: str,
    *,
    topic: str,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    severity: int = 1,
) -> tuple[WeakTopic, bool]:
    """Return (row, created). Repeated errors escalate severity instead of
    creating duplicates."""
    if not topic:
        raise ValueError("topic is required")
    row = (
        db.query(WeakTopic)
        .filter(
            WeakTopic.student_id == student_id,
            WeakTopic.topic == topic,
            WeakTopic.is_active.is_(True),
        )
        .first()
    )
    if row is None:
        row = WeakTopic(
            student_id=student_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
            topic=topic,
            severity=severity,
            errors=1,
            last_error_at=utcnow(),
        )
        db.add(row)
        db.flush()
        return row, True

    row.errors = (row.errors or 0) + 1
    row.severity = min(5, max(row.severity, 1 + row.errors // 2))
    row.last_error_at = utcnow()
    db.flush()
    return row, row.errors == 1


def resolve_weak(db: Session, student_id: str, topic: str) -> None:
    row = (
        db.query(WeakTopic)
        .filter(
            WeakTopic.student_id == student_id,
            WeakTopic.topic == topic,
            WeakTopic.is_active.is_(True),
        )
        .first()
    )
    if row and row.severity <= 1:
        row.is_active = False
        row.resolved_at = utcnow()
        db.flush()


def active_weak(db: Session, student_id: str, limit: int = 10) -> list[WeakTopic]:
    return (
        db.query(WeakTopic)
        .filter(WeakTopic.student_id == student_id, WeakTopic.is_active.is_(True))
        .order_by(WeakTopic.severity.desc(), WeakTopic.errors.desc())
        .limit(limit)
        .all()
    )


# --------------------------------------------------------------------------- #
# streak
# --------------------------------------------------------------------------- #
def study_day_key() -> str:
    return utcnow().date().isoformat()


def touch_streak(db: Session, student_id: str) -> dict[str, Any]:
    row = db.query(StudyStreak).filter(StudyStreak.student_id == student_id).one_or_none()
    if row is None:
        row = StudyStreak(student_id=student_id)
        db.add(row)
        db.flush()

    today = utcnow().date()
    previous_day = row.last_study_day
    if row.last_study_day == today.isoformat():
        return {
            "current": row.current,
            "longest": row.longest,
            "changed": False,
            "previous_day": previous_day,
            "started_new": False,
        }

    yesterday = (today - timedelta(days=1)).isoformat()
    started_new = previous_day is None or previous_day < yesterday
    if row.last_study_day == yesterday:
        row.current += 1
    else:
        row.current = 1
    row.last_study_day = today.isoformat()
    row.longest = max(row.longest or 0, row.current)
    db.flush()
    return {
        "current": row.current,
        "longest": row.longest,
        "changed": True,
        "previous_day": previous_day,
        "started_new": started_new,
    }


def streak_break_check(db: Session, student_id: str) -> dict[str, Any]:
    """Called by the daily coach: marks a broken streak exactly once."""
    row = db.query(StudyStreak).filter(StudyStreak.student_id == student_id).one_or_none()
    if row is None or not row.last_study_day:
        return {"broken": False, "current": 0}
    last = date.fromisoformat(row.last_study_day)
    gap = (utcnow().date() - last).days
    if gap <= 1:
        return {"broken": False, "current": row.current}
    previous = row.current
    row.current = 0
    db.flush()
    return {"broken": previous > 0, "current": 0, "was": previous, "gap": gap}


# --------------------------------------------------------------------------- #
# achievements
# --------------------------------------------------------------------------- #
def _metric_value(db: Session, student_id: str, metric: str) -> float:
    if metric == "sessions":
        return float(
            db.query(StudySession)
            .filter(StudySession.student_id == student_id, StudySession.status == "completed")
            .count()
        )
    if metric == "study_minutes":
        seconds = (
            db.query(StudySession)
            .filter(StudySession.student_id == student_id)
            .with_entities(StudySession.elapsed_seconds)
            .all()
        )
        return sum(s or 0 for s, in seconds) / 60.0
    if metric == "quizzes":
        return float(
            db.query(QuizAttempt)
            .filter(QuizAttempt.student_id == student_id, QuizAttempt.status == "finished")
            .count()
        )
    if metric == "tasks":
        return float(
            db.query(Task)
            .filter(Task.student_id == student_id, Task.status == "completed")
            .count()
        )
    if metric == "streak":
        row = db.query(StudyStreak).filter(StudyStreak.student_id == student_id).one_or_none()
        return float(row.longest if row else 0)
    if metric == "papers":
        from ..db import Paper

        return float(db.query(Paper).filter(Paper.student_id == student_id).count())
    return 0.0


def evaluate_achievements(db: Session, student_id: str) -> list[dict[str, Any]]:
    catalogue = db.query(Achievement).all()
    if not catalogue:
        return []
    earned = {
        row.achievement_id: row
        for row in db.query(StudentAchievement)
        .filter(StudentAchievement.student_id == student_id)
        .all()
    }
    unlocked: list[dict[str, Any]] = []
    for achievement in catalogue:
        value = _metric_value(db, student_id, achievement.metric)
        link = earned.get(achievement.id)
        progress = min(100.0, value / max(achievement.threshold, 1) * 100.0)
        if link is None:
            link = StudentAchievement(
                student_id=student_id, achievement_id=achievement.id, progress=progress
            )
            db.add(link)
        else:
            link.progress = progress
        if progress >= 100 and link.earned_at is None:
            link.earned_at = utcnow()
            unlocked.append(
                {
                    "code": achievement.code,
                    "name": achievement.name,
                    "description": achievement.description,
                    "icon": achievement.icon,
                }
            )
    db.flush()
    for unlocked_item in unlocked:
        bus.emit(
            db,
            student_id,
            EventType.ACHIEVEMENT_EARNED,
            {
                "code": unlocked_item["code"],
                "name": unlocked_item["name"],
                "description": unlocked_item["description"],
                "icon": unlocked_item["icon"],
            },
        )
    return unlocked


# --------------------------------------------------------------------------- #
# reports
# --------------------------------------------------------------------------- #
def progress_report(db: Session, student_id: str) -> dict[str, Any]:
    profile = db.get(StudentProfile, student_id)
    sessions = (
        db.query(StudySession)
        .filter(StudySession.student_id == student_id, StudySession.status == "completed")
        .all()
    )
    total_seconds = sum(s.elapsed_seconds or 0 for s in sessions)
    week_ago = utcnow() - timedelta(days=7)
    week_sessions = [s for s in sessions if s.started_at and s.started_at >= week_ago]
    week_seconds = sum(s.elapsed_seconds or 0 for s in week_sessions)

    by_subject: dict[str, dict[str, Any]] = {}
    for session in sessions:
        if not session.subject_id:
            continue
        bucket = by_subject.setdefault(
            session.subject_id, {"subject_id": session.subject_id, "sessions": 0, "seconds": 0}
        )
        bucket["sessions"] += 1
        bucket["seconds"] += session.elapsed_seconds or 0

    subjects = {
        row.id: row
        for row in db.query(Subject)
        .filter(Subject.id.in_(list(by_subject.keys()) or [""]))
        .all()
    }
    subject_stats = []
    for subject_id, stats in by_subject.items():
        subject = subjects.get(subject_id)
        mastery = (
            db.query(MasteryScore)
            .filter(MasteryScore.student_id == student_id, MasteryScore.subject_id == subject_id)
            .all()
        )
        avg = sum(m.score for m in mastery) / len(mastery) if mastery else None
        subject_stats.append(
            {
                "subject_id": subject_id,
                "name_ar": subject.name_ar if subject else "",
                "color": subject.color if subject else "#2f8ff7",
                "sessions": stats["sessions"],
                "minutes": round(stats["seconds"] / 60),
                "mastery": round(avg, 1) if avg is not None else None,
            }
        )
    subject_stats.sort(key=lambda s: (s["mastery"] is None, s["mastery"] or 0))

    streak = db.query(StudyStreak).filter(StudyStreak.student_id == student_id).one_or_none()
    weak = active_weak(db, student_id, 8)
    mastery = mastery_map(db, student_id)

    return {
        "totals": {
            "sessions": len(sessions),
            "study_minutes": round(total_seconds / 60),
            "week_minutes": round(week_seconds / 60),
            "week_sessions": len(week_sessions),
            "tasks_completed": _metric_value(db, student_id, "tasks"),
        },
        "streak": {
            "current": streak.current if streak else 0,
            "longest": streak.longest if streak else 0,
        },
        "subjects": subject_stats,
        "weak_topics": [
            {
                "topic": w.topic,
                "subject_id": w.subject_id,
                "severity": w.severity,
                "errors": w.errors,
            }
            for w in weak
        ],
        "mastery": mastery,
        "onboarding_step": profile.onboarding_step if profile else 0,
    }


__all__ = [
    "get_mastery",
    "update_mastery",
    "mastery_map",
    "register_weak",
    "resolve_weak",
    "active_weak",
    "touch_streak",
    "streak_break_check",
    "evaluate_achievements",
    "progress_report",
    "MASTERY_WEAK",
    "MASTERY_STRONG",
]

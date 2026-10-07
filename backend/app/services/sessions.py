"""Study sessions: start → focus → finish → feedback → review.

`complete_session` is the centre of the product loop. It emits ONE event and
lets the bus fan out to mastery, streak, review scheduling, achievements,
Mors' expression, the daily summary and notifications — so none of those
concerns are welded to this route.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..db import (
    LearningProfile,
    Lesson,
    StudySession,
    Subject,
    Task,
    utcnow,
)
from ..mors import EventType, PersonalityContext, bus, react
from ..mors.models_helper import queue_message, record_state
from .planner import complete_task, estimate_duration
from .progress import evaluate_achievements, register_weak, touch_streak, update_mastery
from .review import schedule_review

MIN_REGULAR_SESSION = 30
QUICK_SESSION = 15


def start_session(
    db: Session,
    student_id: str,
    *,
    task_id: str | None = None,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    goal: str = "",
    focus_mode: bool = False,
    title: str = "",
) -> StudySession:
    existing = (
        db.query(StudySession)
        .filter(StudySession.student_id == student_id, StudySession.status == "active")
        .first()
    )
    if existing:
        existing.status = "interrupted"
        existing.ended_at = utcnow()
        db.flush()

    lesson = db.get(Lesson, lesson_id) if lesson_id else None
    task = db.get(Task, task_id) if task_id else None
    subject_id = subject_id or (lesson.subject_id if lesson else (task.subject_id if task else None))
    duration = task.duration_minutes if task else (lesson.estimated_minutes if lesson else 45)

    session = StudySession(
        student_id=student_id,
        task_id=task_id,
        subject_id=subject_id,
        lesson_id=lesson_id,
        title=title or (task.title if task else (lesson.title if lesson else "جلسة دراسة")),
        goal=goal or (task.goal if task else ""),
        planned_minutes=duration or 45,
        focus_mode=focus_mode,
        status="active",
        started_at=utcnow(),
    )
    db.add(session)
    db.flush()

    if task and task.status == "pending":
        task.status = "in_progress"
        db.flush()

    result = bus.emit(
        db,
        student_id,
        EventType.STUDY_STARTED,
        {
            "session_id": session.id,
            "subject_id": subject_id,
            "lesson_id": lesson_id,
            "minutes": session.planned_minutes,
            "goal": session.goal,
            "focus_mode": focus_mode,
        },
    )
    session.meta = {"mors": result.get("results", {}).get("mors", {})}
    db.flush()
    return session


def _server_elapsed(session: StudySession) -> int:
    """§2.2 / scheduling-engine: real seconds since the server-set start."""
    return int(max(0, (utcnow() - (session.started_at or utcnow())).total_seconds()))


def heartbeat(db: Session, student_id: str, session_id: str, *, elapsed_seconds: int | None = None) -> StudySession | None:
    session = db.get(StudySession, session_id)
    if session is None or session.student_id != student_id or session.status != "active":
        return None
    # The client may report, but never exceed real time: a lying device clock
    # or a hand-crafted heartbeat cannot manufacture study minutes.
    server_elapsed = _server_elapsed(session)
    if elapsed_seconds is not None:
        accepted = min(max(0, int(elapsed_seconds)), server_elapsed)
        session.elapsed_seconds = max(session.elapsed_seconds or 0, accepted)
    else:
        session.elapsed_seconds = max(session.elapsed_seconds or 0, server_elapsed)
    db.flush()
    return session


def end_session(
    db: Session,
    student_id: str,
    session_id: str,
    *,
    status: str = "completed",
    feedback: str | None = None,
    understanding: float | None = None,
    mistakes: int = 0,
) -> dict[str, Any]:
    session = db.get(StudySession, session_id)
    if session is None or session.student_id != student_id:
        return {"ok": False, "error": "session_not_found"}
    if session.ended_at and session.status != "active":
        return {"ok": False, "error": "already_ended"}

    server_elapsed = _server_elapsed(session)
    if session.elapsed_seconds in (0, None):
        session.elapsed_seconds = server_elapsed
    else:
        session.elapsed_seconds = min(int(session.elapsed_seconds), server_elapsed)

    session.status = status
    session.ended_at = utcnow()
    if feedback:
        session.feedback = feedback
    if understanding is not None:
        session.understanding = max(0.0, min(1.0, understanding))
    session.mistakes = mistakes
    db.flush()

    minutes = round(session.elapsed_seconds / 60)
    lesson = db.get(Lesson, session.lesson_id) if session.lesson_id else None
    subject = db.get(Subject, session.subject_id) if session.subject_id else None

    _update_learning_profile(db, student_id, session)
    streak = touch_streak(db, student_id)
    if streak.get("started_new"):
        previous_day = streak.get("previous_day")
        days_absent = 0
        if previous_day:
            days_absent = max(0, (utcnow().date() - date.fromisoformat(previous_day)).days - 1)
        streak_payload = {
            "streak": streak["current"],
            "longest": streak["longest"],
            "days_absent": days_absent,
        }
        if previous_day:
            bus.emit(db, student_id, EventType.RETURNED_AFTER_ABSENCE, streak_payload)
        bus.emit(db, student_id, EventType.STREAK_CREATED, streak_payload)

    mastery_before = None
    mastery_after = None
    if session.lesson_id:
        from .progress import get_mastery

        before_row = get_mastery(db, student_id, lesson_id=session.lesson_id)
        mastery_before = before_row.score if before_row else None
        if feedback:
            quality = {
                "easy": 5,
                "medium": 4,
                "hard": 2,
                "not_understood": 1,
            }.get(feedback, 3)
            row = update_mastery(
                db,
                student_id,
                subject_id=session.subject_id,
                lesson_id=session.lesson_id,
                topic=lesson.title if lesson else "",
                correct=quality >= 3,
            )
            mastery_after = row.score
            schedule_review(
                db,
                student_id,
                lesson_id=session.lesson_id,
                subject_id=session.subject_id,
                topic=lesson.title if lesson else "",
                quality=quality,
            )
            if quality <= 1 and lesson:
                register_weak(
                    db,
                    student_id,
                    topic=lesson.title,
                    subject_id=session.subject_id,
                    lesson_id=lesson.id,
                    severity=2,
                )

    if session.task_id:
        complete_task(db, student_id, session.task_id, seconds=session.elapsed_seconds)

    event = EventType.STUDY_COMPLETED if status == "completed" else EventType.STUDY_INTERRUPTED
    result = bus.emit(
        db,
        student_id,
        event,
        {
            "session_id": session.id,
            "minutes": minutes,
            "subject": subject.name_ar if subject else "",
            "lesson": lesson.title if lesson else "",
            "subject_id": session.subject_id,
            "lesson_id": session.lesson_id,
            "feedback": session.feedback,
            "mastery_before": mastery_before,
            "mastery_after": mastery_after,
            "mistakes": mistakes,
        },
    )
    achievements = evaluate_achievements(db, student_id)
    db.flush()

    return {
        "ok": True,
        "session": session_summary(session),
        "minutes": minutes,
        "is_quick": minutes < QUICK_SESSION,
        "achievements": achievements,
        "mors": result.get("results", {}).get("mors", {}),
        "suggested_break_minutes": 5 if minutes >= 40 else 0,
    }


def _update_learning_profile(db: Session, student_id: str, session: StudySession) -> None:
    row = db.query(LearningProfile).filter(LearningProfile.student_id == student_id).one_or_none()
    if row is None:
        row = LearningProfile(student_id=student_id)
        db.add(row)
        db.flush()

    minutes = (session.elapsed_seconds or 0) / 60.0
    completed = session.status == "completed"
    row.sessions_completed = (row.sessions_completed or 0) + (1 if completed else 0)
    row.sessions_abandoned = (row.sessions_abandoned or 0) + (0 if completed else 1)
    row.total_study_seconds = (row.total_study_seconds or 0) + int(session.elapsed_seconds or 0)

    total = row.sessions_completed + row.sessions_abandoned
    if total:
        row.session_completion_rate = round(row.sessions_completed / total, 3)
    if minutes > 0:
        samples = max(1, total)
        row.avg_session_minutes = round(
            (row.avg_session_minutes or 0) * (samples - 1) / samples + minutes / samples, 1
        )
        if minutes < 35:
            row.learning_speed = row.learning_speed
    hour = utcnow().hour
    row.best_time_of_day = "morning" if 5 <= hour < 12 else ("afternoon" if 12 <= hour < 17 else "evening")
    db.flush()


def session_summary(session: StudySession) -> dict[str, Any]:
    return {
        "id": session.id,
        "title": session.title,
        "goal": session.goal,
        "subject_id": session.subject_id,
        "lesson_id": session.lesson_id,
        "planned_minutes": session.planned_minutes,
        "elapsed_seconds": session.elapsed_seconds,
        "minutes": round((session.elapsed_seconds or 0) / 60),
        "status": session.status,
        "feedback": session.feedback,
        "understanding": session.understanding,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
    }


def active_session(db: Session, student_id: str) -> StudySession | None:
    return (
        db.query(StudySession)
        .filter(StudySession.student_id == student_id, StudySession.status == "active")
        .first()
    )


def recent_sessions(db: Session, student_id: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = (
        db.query(StudySession)
        .filter(StudySession.student_id == student_id)
        .order_by(StudySession.started_at.desc())
        .limit(limit)
        .all()
    )
    return [session_summary(r) for r in rows]


def adaptive_duration(db: Session, student_id: str) -> dict[str, Any]:
    """If they always abandon 90-minute sessions, stop prescribing 90."""
    row = db.query(LearningProfile).filter(LearningProfile.student_id == student_id).one_or_none()
    if row is None:
        return {"recommended_minutes": 45, "reason": "لا توجد بيانات كافية بعد."}
    rate = row.session_completion_rate or 0.6
    average = row.avg_session_minutes or 45
    if rate < 0.5:
        recommended = max(20, round(average * 0.7 / 5) * 5)
        reason = "جلساتك تنتهي قبل الوقت — قصّر الجلسة وخلّها تنجز."
    elif rate > 0.85 and average < 60:
        recommended = min(120, round((average + 15) / 5) * 5)
        reason = "تنهي جلساتك بسهولة — نقدر نزيد المدة شوي."
    else:
        recommended = max(25, round(average / 5) * 5)
        reason = "الحالي مناسب لمستواك."
    return {"recommended_minutes": recommended, "reason": reason, "completion_rate": rate}


__all__ = [
    "start_session",
    "heartbeat",
    "end_session",
    "active_session",
    "recent_sessions",
    "session_summary",
    "adaptive_duration",
    "MIN_REGULAR_SESSION",
    "QUICK_SESSION",
]

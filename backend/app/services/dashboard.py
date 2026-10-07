"""Home screen payload — one request, everything the student sees first."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..db import (
    MorsMessage,
    QuizAttempt,
    StudySession,
    StudyStreak,
    Task,
    utcnow,
)
from . import notifications as inbox
from .planner import task_payload, what_now
from .progress import active_weak, progress_report
from .review import due_reviews, review_pressure

GREETINGS = {
    "morning": "صباح الخير",
    "afternoon": "مساء الخير",
    "evening": "مساء الخير",
    "night": "ليلة هادئة",
}


def _greeting() -> tuple[str, str]:
    hour = utcnow().hour
    if 5 <= hour < 12:
        part = "morning"
    elif 12 <= hour < 17:
        part = "afternoon"
    elif 17 <= hour < 22:
        part = "evening"
    else:
        part = "night"
    return GREETINGS[part], part


def today_tasks(db: Session, student_id: str, *, day: date | None = None) -> dict[str, Any]:
    day = day or utcnow().date()
    rows = (
        db.query(Task)
        .filter(Task.student_id == student_id, Task.scheduled_date == day)
        .order_by(Task.scheduled_start, Task.priority)
        .all()
    )
    done = [r for r in rows if r.status == "completed"]
    return {
        "date": day.isoformat(),
        "tasks": [task_payload(r) for r in rows],
        "done": len(done),
        "total": len(rows),
        "minutes": sum(r.duration_minutes or 0 for r in rows if r.status != "completed"),
        "completed_minutes": sum(r.duration_minutes or 0 for r in done),
    }


def recent_results(db: Session, student_id: str, limit: int = 5) -> list[dict[str, Any]]:
    rows = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.student_id == student_id, QuizAttempt.status == "finished")
        .order_by(QuizAttempt.finished_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "attempt_id": r.id,
            "quiz_id": r.quiz_id,
            "accuracy": r.accuracy,
            "correct": r.correct_count,
            "wrong": r.wrong_count,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in rows
    ]


def weekly_minutes(db: Session, student_id: str) -> int:
    week_ago = utcnow() - timedelta(days=7)
    rows = (
        db.query(StudySession)
        .filter(StudySession.student_id == student_id, StudySession.status == "completed")
        .all()
    )
    total = sum(
        r.elapsed_seconds or 0
        for r in rows
        if r.started_at and r.started_at >= week_ago
    )
    return round(total / 60)


def home(db: Session, student_id: str) -> dict[str, Any]:
    greeting, part = _greeting()
    state = inbox.mors_state(db, student_id)
    streak = db.query(StudyStreak).filter(StudyStreak.student_id == student_id).first()
    pressure = review_pressure(db, student_id)
    plan = what_now(db, student_id)
    report = progress_report(db, student_id)
    recent = recent_results(db, student_id)
    weak = active_weak(db, student_id, 5)

    delta = None
    if len(recent) >= 2:
        delta = round(recent[0]["accuracy"] - recent[1]["accuracy"], 1)

    return {
        "greeting": greeting,
        "time_of_day": part,
        "mors": state,
        "mors_messages": inbox.pending_messages(db, student_id),
        "streak": {
            "current": streak.current if streak else 0,
            "longest": streak.longest if streak else 0,
        },
        "today": today_tasks(db, student_id),
        "next": plan,
        "reviews": {
            "due": len(due_reviews(db, student_id)),
            "overdue": pressure["overdue"],
            "weak_topics": pressure["weak_topics"][:4],
        },
        "notifications": {"unread": inbox.unread_count(db, student_id)},
        "subjects": report["subjects"],
        "weak_topics": [
            {"topic": w.topic, "severity": w.severity, "errors": w.errors} for w in weak
        ],
        "recent_results": recent,
        "score_delta": delta,
        "weekly_minutes": weekly_minutes(db, student_id),
        "focus_mode": inbox.focus_mode(db, student_id),
        "quiet": inbox.is_quiet(db, student_id),
        "onboarding_step": report.get("onboarding_step", 0),
    }


def weekly_summary(db: Session, student_id: str) -> dict[str, Any]:
    sessions = (
        db.query(StudySession)
        .filter(StudySession.student_id == student_id, StudySession.status == "completed")
        .all()
    )
    week_ago = utcnow() - timedelta(days=7)
    week = [s for s in sessions if s.started_at and s.started_at >= week_ago]
    attempts = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.student_id == student_id, QuizAttempt.status == "finished")
        .order_by(QuizAttempt.finished_at.desc())
        .limit(10)
        .all()
    )
    return {
        "sessions": len(week),
        "minutes": round(sum(s.elapsed_seconds or 0 for s in week) / 60),
        "quizzes": len(attempts),
        "average_accuracy": round(sum(a.accuracy for a in attempts) / len(attempts), 1)
        if attempts
        else None,
        "best": max((a.accuracy for a in attempts), default=0.0),
        "trend": _trend([a.accuracy for a in reversed(attempts)]),
    }


def _trend(values: list[float]) -> str:
    if len(values) < 2:
        return "flat"
    half = len(values) // 2
    first = sum(values[:half]) / half
    second = sum(values[half:]) / (len(values) - half)
    if second - first >= 5:
        return "up"
    if first - second >= 5:
        return "down"
    return "flat"


__all__ = [
    "home",
    "today_tasks",
    "recent_results",
    "weekly_minutes",
    "weekly_summary",
]

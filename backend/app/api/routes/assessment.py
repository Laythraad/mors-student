"""Quiz generation, attempts and reports."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...core.deps import CurrentProfile, DbSession
from ...core.errors import NotFoundError
from ...db import Quiz, QuizAttempt
from ...services import assessment as service

router = APIRouter(prefix="/quiz", tags=["quiz"])


class GenerateIn(BaseModel):
    subject_id: str | None = None
    lesson_id: str | None = None
    title: str = Field(default="", max_length=220)
    kind: str = Field(default="quiz", pattern="^(quiz|exam|practice|diagnostic|daily)$")
    count: int = Field(default=10, ge=1, le=30)
    difficulty: int = Field(default=3, ge=1, le=5)
    types: list[str] = Field(default_factory=lambda: ["mcq"])
    source_scope: str = Field(default="curriculum", pattern="^(curriculum|book|practice|sources)$")


class AnswerIn(BaseModel):
    question_id: str
    answer: str = Field(default="", max_length=1000)
    time_seconds: int = Field(default=0, ge=0, le=7200)
    hint_used: bool = False


class FlagIn(BaseModel):
    kind: str = Field(default="unclear", pattern="^(wrong_answer|unclear|bad_options|other)$")
    detail: str = Field(default="", max_length=500)


@router.post("/generate")
def generate(payload: GenerateIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = service.generate_quiz(
        db,
        profile.id,
        subject_id=payload.subject_id,
        lesson_id=payload.lesson_id,
        title=payload.title,
        kind=payload.kind,
        count=payload.count,
        difficulty=payload.difficulty,
        types=payload.types,
        source_scope=payload.source_scope,
    )
    db.commit()
    return result


# /daily must be declared before /{quiz_id} — FastAPI matches in declaration order
@router.get("/daily")
def daily(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return service.daily_status(db, profile.id)


@router.post("/daily")
def daily_start(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    payload = service.ensure_daily_quiz(db, profile.id)
    db.commit()
    return payload


@router.post("/questions/{question_id}/flag")
def flag(question_id: str, payload: FlagIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = service.flag_question(
        db, profile.id, question_id, kind=payload.kind, detail=payload.detail
    )
    db.commit()
    return result


@router.get("/{quiz_id}")
def get_quiz(quiz_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None or quiz.student_id != profile.id:
        raise NotFoundError("الاختبار غير موجود.")
    return service.quiz_payload(db, quiz, include_answers=False)


@router.get("")
def history(profile: CurrentProfile, db: DbSession, limit: int = 20) -> dict[str, Any]:
    rows = (
        db.query(Quiz)
        .filter(Quiz.student_id == profile.id)
        .order_by(Quiz.created_at.desc())
        .limit(limit)
        .all()
    )
    attempts = {
        a.quiz_id: a
        for a in db.query(QuizAttempt)
        .filter(QuizAttempt.student_id == profile.id, QuizAttempt.status == "finished")
        .order_by(QuizAttempt.finished_at.desc())
        .all()
    }
    return {
        "quizzes": [
            {
                "id": r.id,
                "title": r.title,
                "kind": r.kind,
                "difficulty": r.difficulty,
                "question_count": len(r.questions),
                "subject_id": r.subject_id,
                "lesson_id": r.lesson_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "last_accuracy": attempts[r.id].accuracy if r.id in attempts else None,
            }
            for r in rows
        ]
    }


@router.post("/{quiz_id}/start")
def start(quiz_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    attempt = service.start_attempt(db, profile.id, quiz_id)
    db.commit()
    return {"attempt_id": attempt.id, "status": attempt.status, "max_score": attempt.max_score}


@router.post("/attempts/{attempt_id}/answer")
def answer(attempt_id: str, payload: AnswerIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = service.submit_answer(
        db,
        profile.id,
        attempt_id,
        payload.question_id,
        payload.answer,
        time_seconds=payload.time_seconds,
        hint_used=payload.hint_used,
    )
    db.commit()
    return result


@router.post("/attempts/{attempt_id}/finish")
def finish(attempt_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    report = service.finish_attempt(db, profile.id, attempt_id)
    db.commit()
    return report


@router.get("/attempts/{attempt_id}/report")
def report(attempt_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    attempt = db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.student_id != profile.id:
        raise NotFoundError("المحاولة غير موجودة.")
    return service.attempt_report(db, attempt)


__all__ = ["router"]

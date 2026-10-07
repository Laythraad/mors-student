"""Exam sessions, readiness, mistake book and the question bank."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...core.deps import CurrentProfile, DbSession, ManagerUser
from ...core.errors import NotFoundError
from ...services import bank as bank_service
from ...services import exams as service

router = APIRouter(prefix="/exams", tags=["exams"])


class GenerateIn(BaseModel):
    subject_id: str | None = None
    lesson_id: str | None = None
    chapter_id: str | None = None
    title: str = Field(default="", max_length=220)
    count: int = Field(default=20, ge=1, le=30)
    difficulty: int = Field(default=3, ge=1, le=5)
    duration_minutes: int = Field(default=45, ge=5, le=240)
    kind: str = Field(default="mock", pattern="^(mock|exam|final|practice)$")


class StartIn(BaseModel):
    quiz_id: str
    mode: str = Field(default="mock", pattern="^(mock|practice|final)$")
    exam_id: str | None = None


class AnswerIn(BaseModel):
    question_id: str
    answer: str = Field(default="", max_length=1000)
    time_seconds: int = Field(default=0, ge=0, le=7200)


class MarkIn(BaseModel):
    question_id: str


class BankIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    options: list[str] = Field(default_factory=list, max_length=8)
    answer_index: int = Field(default=0, ge=0, le=7)
    type: str = Field(default="mcq", pattern="^(mcq|true_false|fill_blank|short_answer|problem|essay|calculation)$")
    explanation: str = Field(default="", max_length=4000)
    difficulty: int = Field(default=3, ge=1, le=5)
    topic: str = Field(default="", max_length=220)
    subject_id: str | None = None
    lesson_id: str | None = None
    chapter_id: str | None = None
    source_kind: str = Field(default="ai", pattern="^(official|ai|external|bank)$")
    source_id: str | None = None
    source_url: str = Field(default="", max_length=500)
    year: str = Field(default="", max_length=12)
    page: int | None = Field(default=None, ge=1, le=100000)
    answer_key: str = ""


@router.get("")
def home(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return service.overview(db, profile)


@router.post("/generate")
def generate(payload: GenerateIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = service.generate_exam(
        db,
        profile.id,
        subject_id=payload.subject_id,
        lesson_id=payload.lesson_id,
        chapter_id=payload.chapter_id,
        title=payload.title,
        count=payload.count,
        difficulty=payload.difficulty,
        duration_minutes=payload.duration_minutes,
        kind=payload.kind,
    )
    db.commit()
    return result


@router.post("/start")
def start(payload: StartIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    attempt = service.start_exam(
        db, profile.id, payload.quiz_id, mode=payload.mode, exam_id=payload.exam_id
    )
    db.commit()
    return service.attempt_payload(db, attempt)


@router.get("/attempts/{exam_attempt_id}")
def attempt(exam_attempt_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    payload = service.get_attempt(db, profile.id, exam_attempt_id)
    db.commit()
    return payload


@router.post("/attempts/{exam_attempt_id}/answer")
def answer(
    exam_attempt_id: str, payload: AnswerIn, profile: CurrentProfile, db: DbSession
) -> dict[str, Any]:
    result = service.answer(
        db,
        profile.id,
        exam_attempt_id,
        payload.question_id,
        payload.answer,
        time_seconds=payload.time_seconds,
    )
    db.commit()
    return result


@router.post("/attempts/{exam_attempt_id}/mark")
def mark(
    exam_attempt_id: str, payload: MarkIn, profile: CurrentProfile, db: DbSession
) -> dict[str, Any]:
    result = service.toggle_mark(db, profile.id, exam_attempt_id, payload.question_id)
    db.commit()
    return result


@router.post("/attempts/{exam_attempt_id}/submit")
def submit(exam_attempt_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = service.submit(db, profile.id, exam_attempt_id)
    db.commit()
    return result


@router.get("/readiness")
def readiness_route(
    profile: CurrentProfile, db: DbSession, subject_id: str | None = None
) -> dict[str, Any]:
    return service.readiness(db, profile.id, subject_id)


@router.get("/mistakes")
def mistakes(
    profile: CurrentProfile,
    db: DbSession,
    subject_id: str | None = None,
    active_only: bool = True,
    q: str = Query("", max_length=120),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    return service.list_mistakes(
        db, profile.id, subject_id=subject_id, active_only=active_only, q=q, limit=limit
    )


@router.post("/mistakes/{mistake_id}/resolve")
def resolve(mistake_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = service.resolve_mistake(db, profile.id, mistake_id)
    db.commit()
    return result


@router.get("/bank")
def bank_list(
    _: ManagerUser,
    db: DbSession,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    chapter_id: str | None = None,
    difficulty: int | None = None,
    source_kind: str | None = None,
    status: str | None = None,
    year: str | None = None,
    q: str = Query("", max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    result = bank_service.list_questions(
        db,
        subject_id=subject_id,
        lesson_id=lesson_id,
        chapter_id=chapter_id,
        difficulty=difficulty,
        source_kind=source_kind,
        status=status,
        year=year,
        q=q,
        offset=offset,
        limit=limit,
    )
    return result | {"stats": bank_service.bank_stats(db)}


@router.post("/bank")
def bank_add(payload: BankIn, _: ManagerUser, db: DbSession) -> dict[str, Any]:
    question = bank_service.add_question(db, payload.model_dump())
    db.commit()
    return {
        "id": question.id,
        "status": question.status,
        "dedup_hash": question.dedup_hash,
        "issues": bank_service.validate_question(db, question)["issues"],
    }


@router.post("/bank/{question_id}/validate")
def bank_validate(question_id: str, _: ManagerUser, db: DbSession) -> dict[str, Any]:
    from ...db import Question

    question = db.get(Question, question_id)
    if question is None:
        raise NotFoundError("السؤال غير موجود.")
    return bank_service.validate_question(db, question)


__all__ = ["router"]

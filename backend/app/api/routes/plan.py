"""Study plan, tasks, calendar and exams."""

from __future__ import annotations

from datetime import date as Date
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...core.deps import CurrentProfile, DbSession
from ...core.errors import NotFoundError, ValidationError
from ...db import CalendarEvent, Exam, StudyPlan, utcnow
from ...mors import EventType, bus
from ...services import planner as service

router = APIRouter(prefix="/plan", tags=["plan"])


class GenerateIn(BaseModel):
    days: int = Field(default=7, ge=1, le=30)
    kind: str = "regular"
    title: str = ""
    rationale: str = ""


class MoveIn(BaseModel):
    date: str
    start: str | None = None


class StatusIn(BaseModel):
    status: str = Field(pattern="^(pending|in_progress|completed|skipped|postponed)$")


class ExamIn(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    exam_date: str
    subject_id: str | None = None
    duration_minutes: int = Field(default=90, ge=15, le=400)
    topics: list[str] = Field(default_factory=list)


@router.get("/current")
def current(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    plan = (
        db.query(StudyPlan)
        .filter(StudyPlan.student_id == profile.id, StudyPlan.is_active.is_(True))
        .order_by(StudyPlan.created_at.desc())
        .first()
    )
    if plan is None:
        return {"plan": None, "message": "ما عندك خطة بعد — أنشئ واحدة."}
    return {"plan": service.plan_payload(plan)}


@router.post("/generate")
def generate(payload: GenerateIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    plan = service.generate_plan(
        db,
        profile.id,
        days=payload.days,
        kind=payload.kind,
        title=payload.title,
        rationale=payload.rationale,
    )
    db.commit()
    return {"plan": service.plan_payload(plan)}


@router.post("/recovery")
def recovery(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    summary = service.recovery_plan(db, profile.id)
    db.commit()
    plan = db.get(StudyPlan, summary.get("plan_id")) if summary.get("plan_id") else None
    return {**summary, "plan": service.plan_payload(plan) if plan else None}


@router.post("/exam-countdown/{exam_id}")
def countdown(exam_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    summary = service.exam_countdown_plan(db, profile.id, exam_id)
    db.commit()
    plan = db.get(StudyPlan, summary.get("plan_id")) if summary.get("plan_id") else None
    return {**summary, "plan": service.plan_payload(plan) if plan else None}


@router.get("/what-now")
def what_now(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return service.what_now(db, profile.id)


@router.get("/tasks")
def tasks(profile: CurrentProfile, db: DbSession, day: str | None = None) -> dict[str, Any]:
    from ...db import Task

    q = db.query(Task).filter(Task.student_id == profile.id)
    if day:
        q = q.filter(Task.scheduled_date == Date.fromisoformat(day))
    rows = q.order_by(Task.scheduled_date, Task.scheduled_start).limit(200).all()
    return {"tasks": [service.task_payload(t) for t in rows]}


@router.post("/tasks/{task_id}/complete")
def complete(task_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    task = service.complete_task(db, profile.id, task_id)
    if task is None:
        raise NotFoundError("المهمة غير موجودة.")
    db.commit()
    return {"task": service.task_payload(task)}


@router.post("/tasks/{task_id}/move")
def move(task_id: str, payload: MoveIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    from datetime import datetime

    new_date = Date.fromisoformat(payload.date)
    new_start = None
    if payload.start:
        try:
            new_start = datetime.fromisoformat(payload.start)
        except ValueError as exc:
            raise ValidationError("وقت البدء غير صالح.") from exc
    service.move_task(db, profile.id, task_id, new_date=new_date, new_start=new_start)
    db.commit()
    return {"ok": True}


@router.patch("/tasks/{task_id}/status")
def status(task_id: str, payload: StatusIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    task = service.change_task_status(db, profile.id, task_id, payload.status)
    if task is None:
        raise NotFoundError("المهمة غير موجودة.")
    db.commit()
    return {"task": service.task_payload(task)}


@router.get("/calendar")
def calendar(profile: CurrentProfile, db: DbSession, days: int = Query(30, ge=1, le=90)) -> dict[str, Any]:
    from datetime import timedelta

    start = utcnow().date()
    rows = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.student_id == profile.id,
            CalendarEvent.start_at >= utcnow() - timedelta(days=1),
            CalendarEvent.start_at <= utcnow() + timedelta(days=days),
        )
        .order_by(CalendarEvent.start_at)
        .limit(300)
        .all()
    )
    return {
        "events": [
            {
                "id": r.id,
                "kind": r.kind,
                "title": r.title,
                "start": r.start_at.isoformat() if r.start_at else None,
                "end": r.end_at.isoformat() if r.end_at else None,
                "color": r.color,
                "task_id": r.task_id,
                "exam_id": r.exam_id,
            }
            for r in rows
        ]
    }


@router.get("/exams")
def exams(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    rows = (
        db.query(Exam)
        .filter(Exam.student_id == profile.id)
        .order_by(Exam.exam_date)
        .all()
    )
    today = utcnow().date()
    return {
        "exams": [
            {
                "id": r.id,
                "title": r.title,
                "exam_date": r.exam_date.isoformat(),
                "days_left": max(0, (r.exam_date - today).days),
                "subject_id": r.subject_id,
                "duration_minutes": r.duration_minutes,
                "topics": r.topics or [],
                "status": r.status,
                "score": r.score,
            }
            for r in rows
        ]
    }


@router.post("/exams")
def create_exam(payload: ExamIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    exam_date = Date.fromisoformat(payload.exam_date)
    if exam_date < utcnow().date():
        raise ValidationError("تاريخ الامتحان قديم.")
    exam = Exam(
        student_id=profile.id,
        subject_id=payload.subject_id,
        title=payload.title,
        exam_date=exam_date,
        duration_minutes=payload.duration_minutes,
        topics=[t for t in payload.topics if t][:20],
        status="upcoming",
    )
    db.add(exam)
    db.flush()
    days_left = (exam_date - utcnow().date()).days
    bus.emit(
        db,
        profile.id,
        EventType.EXAM_SCHEDULED,
        {"exam_id": exam.id, "days_left": days_left, "title": exam.title, "subject_id": exam.subject_id},
    )
    db.commit()
    return {"exam_id": exam.id, "days_left": days_left}


@router.delete("/exams/{exam_id}")
def delete_exam(exam_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    exam = db.get(Exam, exam_id)
    if exam is None or exam.student_id != profile.id:
        raise NotFoundError("الامتحان غير موجود.")
    db.delete(exam)
    db.commit()
    return {"ok": True}


__all__ = ["router"]

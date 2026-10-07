"""Study sessions: start → heartbeat → end → feedback → break."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...core.deps import CurrentProfile, DbSession
from ...core.errors import NotFoundError, ValidationError
from ...mors import EventType, PersonalityContext, bus, react
from ...services import sessions as service

router = APIRouter(prefix="/study", tags=["study"])


class StartIn(BaseModel):
    task_id: str | None = None
    subject_id: str | None = None
    lesson_id: str | None = None
    goal: str = Field(default="", max_length=400)
    focus_mode: bool = False
    title: str = Field(default="", max_length=220)


class HeartbeatIn(BaseModel):
    elapsed_seconds: int | None = Field(default=None, ge=0, le=60 * 60 * 12)


class EndIn(BaseModel):
    status: str = Field(default="completed", pattern="^(completed|interrupted|abandoned)$")
    feedback: str | None = Field(default=None, pattern="^(easy|medium|hard|not_understood)$")
    understanding: float | None = Field(default=None, ge=0, le=1)
    mistakes: int = Field(default=0, ge=0, le=99)


class FeedbackIn(BaseModel):
    session_id: str | None = None
    feedback: str = Field(pattern="^(easy|medium|hard|not_understood)$")
    understanding: float | None = Field(default=None, ge=0, le=1)
    comment: str = Field(default="", max_length=600)


@router.post("/start")
def start(payload: StartIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    session = service.start_session(
        db,
        profile.id,
        task_id=payload.task_id,
        subject_id=payload.subject_id,
        lesson_id=payload.lesson_id,
        goal=payload.goal,
        focus_mode=payload.focus_mode,
        title=payload.title,
    )
    db.commit()
    return {"session": service.session_summary(session), "mors": session.meta.get("mors", {})}


@router.get("/active")
def active(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    session = service.active_session(db, profile.id)
    if session is None:
        return {"session": None}
    return {"session": service.session_summary(service.heartbeat(db, profile.id, session.id))}


@router.post("/{session_id}/heartbeat")
def heartbeat(session_id: str, payload: HeartbeatIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    session = service.heartbeat(db, profile.id, session_id, elapsed_seconds=payload.elapsed_seconds)
    if session is None:
        raise NotFoundError("الجلسة غير موجودة أو منتهية.")
    db.commit()
    return {"session": service.session_summary(session)}


@router.post("/{session_id}/end")
def end(session_id: str, payload: EndIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = service.end_session(
        db,
        profile.id,
        session_id,
        status=payload.status,
        feedback=payload.feedback,
        understanding=payload.understanding,
        mistakes=payload.mistakes,
    )
    if not result.get("ok"):
        raise NotFoundError("الجلسة غير موجودة.")
    db.commit()
    return result


@router.get("/recent")
def recent(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return {"sessions": service.recent_sessions(db, profile.id)}


@router.get("/suggested-duration")
def suggested_duration(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return service.adaptive_duration(db, profile.id)


@router.post("/break")
def start_break(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = bus.emit(db, profile.id, EventType.BREAK_STARTED, {"minutes": 5})
    ctx = PersonalityContext(
        event=str(EventType.BREAK_STARTED),
        student_name=profile.user.full_name.split()[0] if profile.user else "",
    )
    reaction = react(ctx, seed=f"break|{profile.id}")
    db.commit()
    return {"mors": reaction.as_dict(), "minutes": 5, "from_event": result.get("results", {}).get("mors", {})}


@router.post("/feedback")
def feedback(payload: FeedbackIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    from ...db import StudySession

    session = None
    if payload.session_id:
        session = db.get(StudySession, payload.session_id)
        if session is None or session.student_id != profile.id:
            raise NotFoundError("الجلسة غير موجودة.")
        session.feedback = payload.feedback
        if payload.understanding is not None:
            session.understanding = payload.understanding
        db.flush()

    result = bus.emit(
        db,
        profile.id,
        EventType.FEEDBACK_SUBMITTED,
        {
            "session_id": payload.session_id,
            "feedback": payload.feedback,
            "comment": payload.comment,
        },
    )
    if not payload.comment and payload.feedback in ("hard", "not_understood"):
        from ...services.progress import active_weak

        weak = active_weak(db, profile.id, 1)
        if weak:
            bus.emit(
                db,
                profile.id,
                EventType.HELP_REQUESTED,
                {"topic": weak[0].topic, "subject_id": weak[0].subject_id, "lesson_id": weak[0].lesson_id},
            )
    db.commit()
    return {"ok": True, "mors": result.get("results", {}).get("mors", {})}


__all__ = ["router"]

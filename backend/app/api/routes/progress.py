"""Dashboard, progress reports, coach brief and exports."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from ...core.deps import CurrentProfile, DbSession
from ...core.errors import NotFoundError
from ...services import coach, dashboard, export as exporter, notifications as inbox
from ...services import progress as service

router = APIRouter(prefix="/progress", tags=["progress"])


class ResolveIn(BaseModel):
    topic: str = Field(min_length=1, max_length=220)


@router.get("/home")
def home(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return dashboard.home(db, profile.id)


@router.get("/report")
def report(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return service.progress_report(db, profile.id)


@router.get("/week")
def week(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return dashboard.weekly_summary(db, profile.id)


@router.get("/weak")
def weak(profile: CurrentProfile, db: DbSession, limit: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
    rows = service.active_weak(db, profile.id, limit)
    return {
        "topics": [
            {
                "id": r.id,
                "topic": r.topic,
                "subject_id": r.subject_id,
                "lesson_id": r.lesson_id,
                "severity": r.severity,
                "errors": r.errors,
                "last_error_at": r.last_error_at.isoformat() if r.last_error_at else None,
            }
            for r in rows
        ]
    }


@router.post("/weak/resolve")
def resolve_weak(payload: ResolveIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    service.resolve_weak(db, profile.id, payload.topic)
    db.commit()
    return {"ok": True}


@router.get("/mastery")
def mastery(profile: CurrentProfile, db: DbSession, subject_id: str | None = None) -> dict[str, Any]:
    return {"mastery": service.mastery_map(db, profile.id, subject_id)}


@router.get("/streak")
def streak(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    from ...db import StudyStreak

    row = db.query(StudyStreak).filter(StudyStreak.student_id == profile.id).one_or_none()
    return {
        "current": row.current if row else 0,
        "longest": row.longest if row else 0,
        "last_study_day": row.last_study_day if row else None,
    }


@router.get("/achievements")
def achievements(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    from ...db import Achievement, StudentAchievement

    links = {
        row.achievement_id: row
        for row in db.query(StudentAchievement).filter(StudentAchievement.student_id == profile.id).all()
    }
    out = []
    for row in db.query(Achievement).order_by(Achievement.threshold).all():
        link = links.get(row.id)
        out.append(
            {
                "code": row.code,
                "name": row.name,
                "description": row.description,
                "icon": row.icon,
                "metric": row.metric,
                "threshold": row.threshold,
                "progress": round(link.progress, 1) if link else 0.0,
                "earned_at": link.earned_at.isoformat() if link and link.earned_at else None,
            }
        )
    return {"achievements": out}


@router.get("/coach/daily")
def daily(profile: CurrentProfile, db: DbSession, deliver: bool = False) -> dict[str, Any]:
    brief = coach.daily_brief(db, profile.id, deliver=deliver)
    if deliver:
        db.commit()
    return brief


@router.get("/coach/actions")
def actions(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return {"actions": coach.action_items(db, profile.id)}


@router.get("/coach/streak")
def streak_brief(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return coach.streak_brief(db, profile.id)


@router.get("/export/json")
def export_json(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return exporter.progress_json(db, profile.id)


@router.get("/export/ics")
def export_ics(profile: CurrentProfile, db: DbSession) -> Response:
    content = exporter.plan_ics(db, profile.id)
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="mors-plan.ics"'},
    )


@router.get("/export/pdf")
def export_pdf(profile: CurrentProfile, db: DbSession) -> Response:
    data = exporter.progress_pdf(db, profile.id)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="mors-report.pdf"'},
    )


__all__ = ["router"]

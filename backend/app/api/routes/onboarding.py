"""Onboarding: profile → subjects → optional diagnostic → first plan.

Every step is resumable; nothing blocks the student from reaching the app.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...core.deps import CurrentProfile, DbSession
from ...core.errors import ValidationError
from ...services import assessment, auth, planner

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

STEPS = ("welcome", "stage", "subjects", "schedule", "diagnostic", "plan", "done")


class ScheduleIn(BaseModel):
    school_start: str | None = None
    school_end: str | None = None
    sleep_start: str | None = None
    sleep_end: str | None = None
    daily_study_minutes: int | None = Field(default=None, ge=20, le=600)
    study_days: list[int] | None = None
    free_windows: list[dict[str, str]] | None = None


class DiagnosticIn(BaseModel):
    subject_ids: list[str] = Field(default_factory=list)
    count: int = Field(default=10, ge=4, le=20)


@router.get("/steps")
def steps(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    from ...db import StudentSubject, StudyPlan

    subjects = (
        db.query(StudentSubject)
        .filter(StudentSubject.profile_id == profile.id, StudentSubject.is_active.is_(True))
        .count()
    )
    plan_exists = (
        db.query(StudyPlan)
        .filter(StudyPlan.student_id == profile.id, StudyPlan.is_active.is_(True))
        .count()
        > 0
    )
    completed = {
        "welcome": profile.onboarding_step >= 1,
        "stage": bool(profile.stage_id),
        "subjects": subjects > 0,
        "schedule": bool(profile.school_start and profile.sleep_start),
        "diagnostic": profile.diagnostic_done,
        "plan": plan_exists,
        "done": profile.onboarding_step >= 99,
    }
    return {
        "current": profile.onboarding_step,
        "steps": [{"key": k, "done": completed[k]} for k in STEPS],
        "progress": round(sum(1 for v in completed.values() if v) / len(STEPS) * 100),
    }


@router.post("/step/{step}")
def advance(step: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    if step not in STEPS:
        raise ValidationError("خطوة غير معروفة.")
    target = STEPS.index(step) + 1
    profile.onboarding_step = max(profile.onboarding_step, target)
    db.flush()
    if step == "plan":
        profile.onboarding_step = 99
        db.commit()
        from ...mors import EventType, bus

        bus.emit(
            db,
            profile.id,
            EventType.ONBOARDING_COMPLETED,
            {"student_name": profile.user.full_name if profile.user else ""},
        )
    else:
        db.commit()
    return {"current": profile.onboarding_step}


@router.put("/schedule")
def schedule(payload: ScheduleIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    auth.update_profile(db, profile, payload.model_dump(exclude_none=True))
    db.commit()
    return {"ok": True}


@router.post("/diagnostic")
def diagnostic(payload: DiagnosticIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    subject_ids = payload.subject_ids
    if not subject_ids:
        from ...db import StudentSubject

        subject_ids = [
            r.subject_id
            for r in db.query(StudentSubject)
            .filter(StudentSubject.profile_id == profile.id, StudentSubject.is_active.is_(True))
            .all()
        ]
    if not subject_ids:
        raise ValidationError("اختر موادك أولاً حتى نقدر نحدد مستواك.")

    result = assessment.diagnostic_quiz(db, profile.id, subject_ids=subject_ids, count=payload.count)
    from ...mors import EventType, bus

    bus.emit(db, profile.id, EventType.DIAGNOSTIC_COMPLETED, {"quiz_id": result["id"]})
    db.commit()
    return result


@router.post("/first-plan")
def first_plan(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    plan = planner.generate_plan(db, profile.id, days=7, kind="regular")
    db.commit()
    return planner.plan_payload(plan)


@router.get("/recommend")
def recommend(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    """Suggest subjects for the student's stage/branch before they pick."""
    from ...db import Branch, StudentSubject, Subject

    if profile.branch_id is None:
        return {"subjects": [], "message": "اختر مرحلتك وفرعك أولاً."}
    chosen = {
        r.subject_id
        for r in db.query(StudentSubject).filter(StudentSubject.profile_id == profile.id).all()
    }
    rows = (
        db.query(Subject)
        .filter(Subject.branch_id == profile.branch_id, Subject.is_active.is_(True))
        .order_by(Subject.sort_order)
        .all()
    )
    return {
        "subjects": [
            {"id": r.id, "name_ar": r.name_ar, "color": r.color, "icon": r.icon, "chosen": r.id in chosen}
            for r in rows
        ],
        "stage": db.get(Branch, profile.branch_id).name_ar if db.get(Branch, profile.branch_id) else "",
    }


__all__ = ["router"]

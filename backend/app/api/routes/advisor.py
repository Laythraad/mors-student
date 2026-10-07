"""Student advisor (§22–§24, §58, §88–§92): report, weekly review, actions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...core.deps import CurrentProfile, DbSession
from ...services import advisor as service

router = APIRouter(prefix="/advisor", tags=["advisor"])


@router.get("")
def overview(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return service.overview(db, profile.id)


@router.get("/report")
def report(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return service.success_report(db, profile.id)


@router.get("/weekly")
def weekly(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return service.weekly_review(db, profile.id)


@router.get("/steps")
def steps(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return {
        "steps": service.steps(db, profile.id),
        "plan_health": service.plan_health(db, profile.id),
        "priorities": service.priorities(db, profile.id),
    }


@router.post("/steps/{key}/apply")
def apply(key: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = service.apply_step(db, profile.id, key)
    db.commit()
    return result

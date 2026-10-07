"""Admin & CMS endpoints — role-gated, audited, no student access."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...config import settings
from ...core.deps import AdminUser, DbSession
from ...core.errors import ValidationError
from ...services import admin as service
from ...services import assessment as assessment_service
from ...services import publishing
from ...services import scheduler as scheduler_service
from ...services import videos as videos_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[])


class PromptIn(BaseModel):
    template: str = Field(min_length=40, max_length=20000)
    model_tier: str | None = Field(default=None, pattern="^(fast|primary|reasoning|vision)$")


class SettingIn(BaseModel):
    value: Any
    description: str = Field(default="", max_length=300)


class UserPatchIn(BaseModel):
    is_active: bool


@router.get("/prompts")
def prompts(db: DbSession, admin: AdminUser) -> dict[str, Any]:
    return {"prompts": service.list_prompts(db)}


@router.put("/prompts/{key}")
def update_prompt(key: str, payload: PromptIn, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    result = service.update_prompt(
        db, key, template=payload.template, updated_by=admin.id, model_tier=payload.model_tier
    )
    db.commit()
    return result


@router.delete("/prompts/{key}")
def reset_prompt(key: str, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    result = service.reset_prompt(db, key)
    db.commit()
    return result


@router.get("/stats")
def stats(db: DbSession, admin: AdminUser) -> dict[str, Any]:
    return service.curriculum_stats(db)


@router.get("/usage")
def usage(db: DbSession, admin: AdminUser, days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    return service.ai_usage(db, days=days)


@router.get("/events")
def events(
    db: DbSession,
    admin: AdminUser,
    limit: int = Query(50, ge=1, le=200),
    event_type: str | None = None,
) -> dict[str, Any]:
    return {"events": service.recent_events(db, limit=limit, event_type=event_type)}


@router.get("/users")
def users(db: DbSession, admin: AdminUser, q: str = "", limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    return {"users": service.list_users(db, query=q, limit=limit)}


@router.patch("/users/{user_id}")
def patch_user(user_id: str, payload: UserPatchIn, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    result = service.set_user_active(db, user_id, payload.is_active)
    db.commit()
    return result


@router.get("/settings/{key}")
def get_setting(key: str, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    if not key or len(key) > 80:
        raise ValidationError("مفتاح الإعداد غير صالح.")
    return {"key": key, "value": service.get_setting(db, key)}


@router.put("/settings/{key}")
def put_setting(key: str, payload: SettingIn, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    value = service.set_setting(db, key, payload.value, description=payload.description)
    db.commit()
    return {"key": key, "value": value}


@router.get("/content-reports")
def content_reports(
    db: DbSession, admin: AdminUser, status: str | None = Query(None, pattern="^(open|resolved)$")
) -> dict[str, Any]:
    return videos_service.list_content_reports(db, status=status)


@router.post("/content-reports/{report_id}/resolve")
def resolve_content_report(report_id: str, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    result = videos_service.resolve_content_report(db, report_id)
    db.commit()
    return result


@router.get("/question-flags")
def question_flags(
    db: DbSession, admin: AdminUser, status: str | None = Query(None, pattern="^(open|resolved)$")
) -> dict[str, Any]:
    return assessment_service.list_question_flags(db, status=status)


@router.post("/question-flags/{flag_id}/resolve")
def resolve_question_flag(flag_id: str, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    result = assessment_service.resolve_question_flag(db, flag_id)
    db.commit()
    return result


# --------------------------------------------------------------------------- #
# content publication pipeline (§81/§83)
# --------------------------------------------------------------------------- #
class DraftIn(BaseModel):
    entity: str = Field(pattern="^(subject|chapter|unit|lesson|source|teacher|video|course)$")
    payload: dict[str, Any] = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=255)
    publish_at: datetime | None = None


class DraftPatchIn(BaseModel):
    payload: dict[str, Any] | None = None
    title: str | None = Field(default=None, max_length=255)


class DraftReviewIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=400)
    publish_at: datetime | None = None


@router.post("/drafts")
def create_draft(body: DraftIn, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    result = publishing.create_draft(
        db,
        entity=body.entity,
        payload=body.payload,
        title=body.title,
        publish_at=body.publish_at,
        created_by=admin.id,
    )
    db.commit()
    return result


@router.get("/drafts")
def list_drafts(
    db: DbSession,
    admin: AdminUser,
    status: str | None = Query(
        None, pattern="^(draft|processing|validated|scheduled|published|rejected)$"
    ),
    entity: str | None = Query(None, pattern="^(subject|chapter|unit|lesson|source|teacher|video|course)$"),
    q: str = Query("", max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return publishing.list_drafts(db, status=status, entity=entity, q=q, limit=limit, offset=offset)


@router.patch("/drafts/{draft_id}")
def patch_draft(
    draft_id: str, body: DraftPatchIn, db: DbSession, admin: AdminUser
) -> dict[str, Any]:
    result = publishing.update_draft(db, draft_id, payload=body.payload, title=body.title)
    db.commit()
    return result


@router.post("/drafts/{draft_id}/process")
def process_draft(draft_id: str, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    result = publishing.process_draft(db, draft_id)
    db.commit()
    return result


@router.post("/drafts/{draft_id}/review")
def review_draft(draft_id: str, body: DraftReviewIn, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    result = publishing.review_draft(
        db,
        draft_id,
        approve=body.approve,
        note=body.note,
        publish_at=body.publish_at,
        reviewer=admin.id,
    )
    db.commit()
    return result


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: str, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    result = publishing.delete_draft(db, draft_id)
    db.commit()
    return result


# --------------------------------------------------------------------------- #
# background jobs (§126/§132)
# --------------------------------------------------------------------------- #
@router.get("/scheduler")
def scheduler_status(db: DbSession, admin: AdminUser) -> dict[str, Any]:
    return {
        "enabled": settings.scheduler_enabled,
        "interval_seconds": settings.scheduler_interval_seconds,
        "jobs": scheduler_service.jobs_status(db),
    }


@router.post("/scheduler/{job}/run")
def scheduler_run(job: str, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    result = scheduler_service.run_job(db, job)
    db.commit()
    return result


__all__ = ["router"]
